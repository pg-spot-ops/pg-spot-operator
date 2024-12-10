import datetime
import json
import logging
import math
import os
import shutil
import signal
import stat
import subprocess
import time

import yaml
from dateutil.parser import isoparse

from pg_spot_operator import cloud_api, cmdb, constants, manifests
from pg_spot_operator.cloud_impl import aws_client
from pg_spot_operator.cloud_impl.aws_client import set_access_keys
from pg_spot_operator.cloud_impl.aws_s3 import (
    s3_clean_bucket_path_if_exists,
    s3_try_create_bucket_if_not_exists,
)
from pg_spot_operator.cloud_impl.aws_spot import (
    attach_pricing_info_to_instance_type_info,
    get_backing_vms_for_instances_if_any,
    resolve_instance_type_info,
    try_get_monthly_ondemand_price_for_sku,
)
from pg_spot_operator.cloud_impl.aws_vm import (
    delete_network_interface,
    delete_volume_in_region,
    ensure_spot_vm,
    get_addresses,
    get_all_active_operator_instances_in_region,
    get_non_self_terminating_network_interfaces,
    get_operator_volumes_in_region,
    release_address_by_allocation_id_in_region,
    terminate_instances_in_region,
)
from pg_spot_operator.cloud_impl.cloud_structs import InstanceTypeInfo
from pg_spot_operator.cmdb import get_instance_connect_string, get_ssh_connstr
from pg_spot_operator.constants import (
    BACKUP_TYPE_PGBACKREST,
    DEFAULT_CONFIG_DIR,
    DEFAULT_INSTANCE_SELECTION_STRATEGY,
    MF_SEC_VM_STORAGE_TYPE_LOCAL,
    SPOT_OPERATOR_EXPIRES_TAG,
)
from pg_spot_operator.instance_type_selection import InstanceTypeSelection
from pg_spot_operator.manifests import InstanceManifest
from pg_spot_operator.util import (
    check_ssh_ping_ok,
    merge_action_output_params,
    merge_user_and_tuned_non_conflicting_config_params,
    run_process_with_output,
    space_pad_manifest,
    try_rm_file_if_exists,
)

MAX_PARALLEL_ACTIONS = 2
ACTION_MAX_DURATION = 600
VM_KEEPALIVE_SCANNER_INTERVAL_S = 60
ACTION_HANDLER_TEMP_SPACE_ROOT = "~/.pg-spot-operator/tmp"
ANSIBLE_DEFAULT_ROOT_PATH = "./ansible"

logger = logging.getLogger(__name__)

default_vault_password_file: str = ""
dry_run: bool = False
operator_startup_time = time.time()
ansible_root_path: str = ANSIBLE_DEFAULT_ROOT_PATH
operator_config_dir: str = DEFAULT_CONFIG_DIR


class NoOp(Exception):
    pass


class UserExit(Exception):
    pass


def preprocess_ensure_vm_action(
    m: InstanceManifest,
    existing_instance_info: dict | None = None,
) -> list[InstanceTypeInfo]:
    """Resolve the manifest HW reqs to instance types.
    If existing / running instance info given, only consider that InstanceType - just need the CPU etc details
    """

    if existing_instance_info:
        cheapest_skus = [
            resolve_instance_type_info(
                existing_instance_info["InstanceType"],
                m.region,
                existing_instance_info.get("Placement", {}).get(
                    "AvailabilityZone", ""
                ),
            )
        ]
        cheapest_skus = attach_pricing_info_to_instance_type_info(
            cheapest_skus
        )
    else:
        cheapest_skus = (
            cloud_api.resolve_hardware_requirements_to_instance_types(m)
        )

    if not cheapest_skus:
        raise Exception(
            f"No SKUs matching HW requirements found for instance {m.instance_name} in {m.cloud} region {m.region}"
        )

    sku = cheapest_skus[0]

    logger.info(
        "%s SKU %s (%s) in availability zone %s for a monthly Spot price of $%s",
        "Found existing" if existing_instance_info else "Selected new",
        sku.instance_type,
        sku.arch,
        sku.availability_zone,
        sku.monthly_spot_price,
    )
    logger.info(
        "SKU %s main specs - vCPU: %s, RAM: %s %s, instance storage: %s %s",
        sku.instance_type,
        sku.cpu,
        sku.ram_mb if sku.ram_mb < 1024 else int(sku.ram_mb / 1024),
        "MiB" if sku.ram_mb < 1024 else "GB",
        f"{sku.instance_storage} GB" if sku.instance_storage else "EBS only",
        sku.storage_speed_class if sku.instance_storage else "",
    )
    if not sku.monthly_ondemand_price:
        sku.monthly_ondemand_price = try_get_monthly_ondemand_price_for_sku(
            m.region, sku.instance_type
        )

    if sku.monthly_ondemand_price and sku.monthly_spot_price:
        spot_discount = (
            100.0
            * (sku.monthly_spot_price - sku.monthly_ondemand_price)
            / sku.monthly_ondemand_price
        )
        logger.info(
            "Current Spot vs Ondemand discount rate: %s%% ($%s vs $%s), approx. %sx to non-HA RDS",
            round(spot_discount, 1),
            sku.monthly_spot_price,
            sku.monthly_ondemand_price,
            math.ceil(
                sku.monthly_ondemand_price / sku.monthly_spot_price * 1.5
            ),
        )
    if sku.eviction_rate_group_label:
        logger.info(
            "Current expected monthly eviction rate range: %s",
            sku.eviction_rate_group_label,
        )

    return cheapest_skus


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def get_ansible_inventory_file_str_for_action(
    action: str, m: InstanceManifest
) -> str:
    groups: dict = {"all": {"hosts": {}}}
    logging.debug(
        "Putting together required inventory for action %s of %s ...",
        action,
        m.instance_name,
    )
    if action in [
        constants.ACTION_ENSURE_VM,
        constants.ACTION_TERMINATE_VM,
        constants.ACTION_DESTROY_INSTANCE,
        constants.ACTION_DESTROY_BACKUPS,
    ]:
        groups["all"]["hosts"]["localhost"] = {}
        return yaml.dump(groups, Dumper=NoAliasDumper)

    vm = cmdb.get_latest_vm_by_uuid(m.uuid)
    if not vm:
        raise Exception(
            f"No active VM found for instance {m.instance_name} to compile an inventory file"
        )
    host_vars = {"ansible_user": vm.login_user}
    if vm.ip_public:
        host_vars["ansible_host"] = vm.ip_public
    if m.ansible.private_key:
        host_vars["ansible_ssh_private_key_file"] = m.ansible.private_key

    groups["all"]["hosts"][vm.ip_private] = host_vars

    return yaml.dump(groups, Dumper=NoAliasDumper)


def generate_ansible_inventory_file_for_action(
    action: str, m: InstanceManifest, temp_workdir: str
):
    """Places an inventory file into temp_workdir"""
    if m.vm.host and m.vm.login_user:
        inventory = f"{m.vm.host} ansible_user={m.vm.login_user}" + (
            f" ansible_ssh_private_key_file={m.ansible.private_key}"
            if m.ansible.private_key
            else ""
        )
    elif dry_run:
        inventory = "dummy"
    else:
        inventory = get_ansible_inventory_file_str_for_action(action, m)
    if not inventory:
        raise Exception(
            f"Could not compile inventory for action {action} of instance {m.instance_name}"
        )

    with open(os.path.join(temp_workdir, "inventory"), "w") as f:
        f.write(inventory)
    logging.debug(
        "Wrote Ansible inventory to: %s",
        os.path.join(temp_workdir, "inventory"),
    )


def populate_temp_workdir_for_action_exec(
    action: str,
    manifest: InstanceManifest,
    temp_workdir_root: str,
) -> str:
    """Create a temp copy of the original handler folder as executions require input / produce output
    Also the original manifest + override one will be placed at "input/instance_manifest.yml",
    and for runnables additionally the manifest will be split into flat key-value files under "input"
    """
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    temp_workdir = os.path.join(
        os.path.expanduser(temp_workdir_root),
        manifest.instance_name,
        action,
        now_str,
    )

    logging.debug("Ensuring temp exec dir %s ...", temp_workdir)
    os.makedirs(temp_workdir, exist_ok=True)

    handler_dir_to_fork = os.path.expanduser(
        os.path.join(ansible_root_path, manifest.api_version)
    )
    if not os.path.exists(handler_dir_to_fork):
        raise Exception(f"Ansible folder at {handler_dir_to_fork} not found")
    # Copy the whole Ansible dir for now into temp dir
    logging.debug(
        "Copying Ansible dir %s to temp exec dir %s ...",
        handler_dir_to_fork,
        temp_workdir,
    )
    shutil.copytree(handler_dir_to_fork, temp_workdir, dirs_exist_ok=True)

    for dir in [
        os.path.join(temp_workdir, "input"),
        os.path.join(temp_workdir, "output"),
    ]:
        shutil.rmtree(
            os.path.join(dir), ignore_errors=True
        )  # Clean vars from previous run if any
        os.makedirs(dir, exist_ok=True)

    with open(
        os.path.join(temp_workdir, "group_vars/all", "instance_manifest.yml"),
        "w",
    ) as f:
        f.write(
            "---\ninstance_manifest:\n"
            + space_pad_manifest(manifest.original_manifest)
        )

    if logger.root.level == logging.DEBUG:  # Some extra Ansible log output
        manifest.session_vars["debug"] = True
    if manifest.session_vars:
        with open(
            os.path.join(
                temp_workdir, "group_vars/all", "engine_overrides.yml"
            ),
            "w",
        ) as f:
            f.write(yaml.dump({"engine_overrides": manifest.session_vars}))

    return temp_workdir


def collect_output_params_from_handler_temp_dir(
    exec_temp_dir: str, action: str
) -> dict:
    """Return keys from exec dir 'output' subfolder if any. No nested folders expected"""
    out_params: dict = {}

    outfiles_path = os.path.join(exec_temp_dir, "output")
    if not os.path.exists(outfiles_path):
        logger.info(
            "Could not collect out params from action %s tempdir %s, 'output' folder not found",
            action,
            exec_temp_dir,
        )
        return out_params

    for dirpath, dirs, files in os.walk(outfiles_path):
        for kf in files:
            with open(os.path.join(dirpath, kf)) as vf:
                outdata = vf.read()
                out_params[kf] = outdata.rstrip()
    return out_params


def display_connect_strings(m: InstanceManifest):
    logger.info("Instance %s setup completed", m.instance_name)

    m.decrypt_secrets_if_any()

    connstr_private, connstr_public = cmdb.get_instance_connect_strings(m)
    if connstr_private:
        logger.info(
            "*** PRIVATE Postgres connect string *** - '%s'", connstr_private
        )
    if connstr_public:
        logger.info(
            "*** PUBLIC Postgres connect string *** - '%s'", connstr_public
        )

    logger.info("*** SSH connect string *** - '%s'", get_ssh_connstr(m))

    if m.monitoring.grafana.enabled:
        vm = cmdb.get_latest_vm_by_uuid(m.uuid)
        primary_ip = "localhost"
        if vm and m.monitoring.grafana.externally_accessible:
            primary_ip = vm.ip_public or vm.ip_private
        grafana_url = f"{m.monitoring.grafana.protocol}://{primary_ip}:3000/"
        logger.info("*** GRAFANA URL *** - '%s'", grafana_url)


def register_results_in_cmdb(
    action: str, output_params_merged: dict, m: InstanceManifest
) -> None:
    if action == constants.ACTION_DESTROY_INSTANCE:
        cmdb.finalize_destroy_instance(m)
        cmdb.mark_manifest_snapshot_as_succeeded(m)
    elif action == constants.ACTION_INSTANCE_SETUP:
        cmdb.mark_manifest_snapshot_as_succeeded(m)


def run_ansible_handler(
    action: str,
    temp_workdir: str,
    executable_full_path: str,
    m: InstanceManifest,
) -> tuple[int, dict]:
    """Returns Ansible process retcode + output params if any"""
    p: subprocess.Popen
    stdout = None

    try:
        # https://alexandra-zaharia.github.io/posts/kill-subprocess-and-its-children-on-timeout-python/ works ??
        # logging.debug("Starting handler at %s", executable_full_path)
        p = subprocess.Popen(
            [executable_full_path, str(ACTION_MAX_DURATION)],
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=temp_workdir,
            text=True,
        )
        stdout, _ = p.communicate(timeout=ACTION_MAX_DURATION)
    except subprocess.TimeoutExpired:
        logging.error(
            "Handler %s ran over max duration, terminating the process ...",
            executable_full_path,
        )
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        logging.exception(
            "Exception in handler %s, terminating the process ...",
            executable_full_path,
        )
        logging.debug(p.stdout) if p and p.stdout else None
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)

    # if p and p.stdout:
    #     logging.debug(p.stdout)

    if not p or p.returncode != 0:
        logging.error(
            "Handler at %s failed",
            executable_full_path,
        )
        return p.returncode, {}

    logging.debug(
        "Handler %s finished - retcode: %s", executable_full_path, p.returncode
    )

    output_params = collect_output_params_from_handler_temp_dir(
        temp_workdir, action
    )
    merged_output_params = merge_action_output_params(
        output_params, m.session_vars
    )

    register_results_in_cmdb(action, merged_output_params, m)

    return p.returncode, merged_output_params


def generate_ansible_run_script_for_action(
    action: str, temp_workdir: str, m: InstanceManifest
) -> str:
    """Currently invoking Ansible via Bash but might want to look at ansible-runner later"""
    extra_args = ""
    if not m.vault_password_file and default_vault_password_file:
        m.vault_password_file = os.path.expanduser(default_vault_password_file)
    if m.vault_password_file:
        extra_args = "--vault-password-file " + m.vault_password_file
    if logger.root.level == logging.DEBUG:  # Some extra Ansible log output
        extra_args += " -v"
    run_template = f"""#!/bin/bash

echo "Starting at `date`"

set -e

EXTRA_ARGS="{extra_args}"

ansible-galaxy install -r requirements.yml

echo "ansible-playbook -i inventory --ssh-common-args '\\-o UserKnownHostsFile=/dev/null \\-o StrictHostKeyChecking=no' $EXTRA_ARGS {action}.yml"
truncate -s0 ansible.log
ansible-playbook -i inventory --ssh-common-args '\\-o UserKnownHostsFile=/dev/null \\-o StrictHostKeyChecking=no' $EXTRA_ARGS {action}.yml

echo "Done at `date`"
"""
    exec_full_path = os.path.join(temp_workdir, str(action) + ".sh")
    with open(exec_full_path, "w") as f:
        f.writelines(run_template)
    st = os.stat(exec_full_path)
    os.chmod(exec_full_path, st.st_mode | stat.S_IEXEC)
    return exec_full_path


def apply_tuning_profile(
    mf: InstanceManifest, tuning_profiles_path: str = "./tuning_profiles"
) -> list[str]:
    """Executes the tuning profile if exists and returns lines that would be added to postgres.config_lines"""
    if not mf.postgres.tuning_profile or mf.postgres.tuning_profile == "none":
        return []
    profile_path_to_run = os.path.join(
        tuning_profiles_path,
        mf.postgres.tuning_profile.strip().lower() + ".py",
    )
    if not os.path.exists(profile_path_to_run):
        logger.warning(
            "Tuning profile %s not found from %s, skipping tuning for instance %s",
            mf.postgres.tuning_profile,
            profile_path_to_run,
            mf.instance_name,
        )
        return []

    tuning_input: dict = (
        mf.vm.model_dump()
    )  # Default fall back of tuning by HW min reqs from user
    if mf.vm.instance_types:  # Use actual HW specs for tuning if available
        try:
            ins_type_info = resolve_instance_type_info(
                mf.vm.instance_types[0], mf.region
            )
            tuning_input = {
                "cpu_min": ins_type_info.cpu,
                "ram_min": int(ins_type_info.ram_mb / 1000),
                "storage_type": mf.vm.storage_type,
                "storage_speed_class": ins_type_info.storage_speed_class,
            }
        except Exception:
            logger.error(
                "Failed to fetch actual HW details, tuning Postgres based on user HW reqs"
            )

    tuning_input["cloud"] = mf.cloud
    tuning_input["postgres_version"] = mf.postgres.version
    tuning_input["user_tags"] = mf.user_tags
    logger.debug("Config tuning input: %s", tuning_input)

    tuning_input_json_str = json.dumps(tuning_input)
    rc, output = run_process_with_output(
        profile_path_to_run, [tuning_input_json_str]
    )
    logger.debug("Config tuning output: %s", "\n" + output.strip())
    if rc != 0:
        logger.warning(
            "Failed to apply tuning profile %s to instance %s. Output: %s",
            mf.postgres.tuning_profile,
            mf.instance_name,
            output,
        )
        return []  # No showstopping for now
    return [line for line in output.split("\n") if line]


def apply_postgres_config_tuning_to_manifest(
    action: str | None, m: InstanceManifest
) -> None:
    if (
        action == constants.ACTION_INSTANCE_SETUP
        and m.postgres.tuning_profile
        and m.postgres.tuning_profile.strip().lower() != "none"
    ):
        logger.info(
            "Applying Postgres tuning profile '%s' to given hardware ...",
            m.postgres.tuning_profile,
        )
        tuned_config_lines = apply_tuning_profile(m)
        logger.info(
            "%s config lines will be added to postgresql.conf",
            len(tuned_config_lines),
        )
        merged_config_lines = (
            merge_user_and_tuned_non_conflicting_config_params(
                tuned_config_lines,
                m.postgres.config_lines.copy(),
            )
        )
        if merged_config_lines:
            if "postgres" not in m.session_vars:
                m.session_vars["postgres"] = {}
            m.session_vars["postgres"]["config_lines"] = merged_config_lines


def clean_up_old_logs_if_any(
    config_dir: str = operator_config_dir, old_threshold_days: int = 7
):
    """Leaves empty instance_name/action folders in place though to indicate what operations have happened / tried
    on which instances
    """
    tmp_path = os.path.expanduser(os.path.join(config_dir, "tmp"))
    logger.debug(
        "Cleaning up old tmp Ansible action logs from %s if any ...", tmp_path
    )
    for dirpath, dirs, files in os.walk(tmp_path):
        for (
            d
        ) in (
            dirs
        ):  # /home/krl/.pg-spot-operator/tmp/pg1/single_instance_setup/2024-10-02_0900/ansible.log
            if not (d.startswith("20") and "-" in d):  # 2024-10-02_0900
                continue
            dt = isoparse(d)
            if dt < (
                datetime.datetime.utcnow()
                - datetime.timedelta(days=old_threshold_days)
            ):
                expired_path = os.path.expanduser(os.path.join(dirpath, d))
                logger.debug(
                    "Removing expired action handler tmp files from %s ...",
                    expired_path,
                )
                shutil.rmtree(expired_path, ignore_errors=True)


def run_action(action: str, m: InstanceManifest) -> tuple[bool, dict]:
    """Returns: (OK, action outputs)
    Steps:
    - Copy handler folder to a temp directory
    - Move manifests to "inputs" folder
    - Start a subprocess and add it to actions_in_progress
    - Collect "output" folder contents on successful exit
    """

    logging.debug(
        "Starting Ansible action %s for instance %s ...",
        action,
        m.instance_name,
    )

    apply_postgres_config_tuning_to_manifest(action, m)

    temp_workdir = populate_temp_workdir_for_action_exec(
        action, m, ACTION_HANDLER_TEMP_SPACE_ROOT
    )

    generate_ansible_inventory_file_for_action(action, m, temp_workdir)

    executable_full_path = generate_ansible_run_script_for_action(
        action, temp_workdir, m
    )

    if dry_run:
        logger.info(
            "Skipping action %s for instance %s as in --dry-run mode",
            action,
            m.instance_name,
        )
        return True, {}

    logger.info(
        "Starting action handler %s for instance %s, log at %s",
        action,
        m.instance_name,
        os.path.join(temp_workdir, "ansible.log"),
    )
    logger.info("SSH connect string: %s", get_ssh_connstr(m))

    rc, outputs = run_ansible_handler(
        action, temp_workdir, executable_full_path, m
    )

    if rc == 0:

        display_connect_strings(m)

        clean_up_old_logs_if_any(
            old_threshold_days=0
        )  # To avoid possibility of unencrypted secrets hanging around for too long

    return rc == 0, outputs


def apply_short_life_time_instances_reordering(
    resolved_instance_types: list[InstanceTypeInfo],
    short_lifetime_instance_types: list[tuple[str, str]],
    instance_selection_strategy: str = DEFAULT_INSTANCE_SELECTION_STRATEGY,
) -> list[InstanceTypeInfo]:
    """The idea here is to reorder the resolved instances shortlist so that instance types / zones that didn't live
    too long would be tried last, even if they were cheaper
    """
    if not short_lifetime_instance_types:
        return resolved_instance_types

    logger.debug(
        "Reordering resolved instances shortlist to prefer recently NOT evicted instance types. Original shortlist: %s",
        [
            (y.instance_type, y.availability_zone)
            for y in resolved_instance_types
        ],
    )

    filtered = [
        x
        for x in resolved_instance_types
        if (x.instance_type, x.availability_zone)
        not in short_lifetime_instance_types
    ]

    if (
        not filtered
    ):  # Handle a more rare case where the whole resolved instance types short-list is suffering from
        # Spot evictions -> prefer low eviction rate and highest price
        if instance_selection_strategy != "eviction-rate":
            instance_selection_strategy_cls = (
                InstanceTypeSelection.get_selection_strategy("eviction-rate")
            )

            filtered = instance_selection_strategy_cls.execute(
                resolved_instance_types
            )
            logger.warning(
                "Temporarily preferring low eviction rate instances within the shortlist as last 30min launches had short lifetime"
            )
            logger.warning(
                "Reordered shortlist: %s",
                [(x.instance_type, x.availability_zone) for x in filtered],
            )
    else:
        # Add back short life time instances
        for y in resolved_instance_types:
            if (
                y.instance_type,
                y.availability_zone,
            ) in short_lifetime_instance_types:
                filtered.append(y)
    logger.debug(
        "Reordered shortlist: %s",
        [(x.instance_type, x.availability_zone) for x in filtered],
    )
    return filtered


def ensure_vm(m: InstanceManifest) -> tuple[bool, str]:
    """Make sure we have a VM
    Returns True if a VM was created / recreated + Provider ID
    """
    logger.debug(
        "Ensuring instance %s (%s) %s has a backing VM ...",
        m.instance_name,
        m.cloud,
        m.uuid,
    )
    backing_instances = get_backing_vms_for_instances_if_any(
        m.region, m.instance_name
    )
    if backing_instances:
        if len(backing_instances) > 1:
            raise Exception(
                f"A single backing instance expected - got: {backing_instances}"
            )  # TODO take latest by creation date
        vm = cmdb.get_latest_vm_by_uuid(m.uuid)
        instance_id = backing_instances[0]["InstanceId"]
        ip_priv = backing_instances[0]["PrivateIpAddress"]
        ip_pub = backing_instances[0].get("PublicIpAddress")
        if vm and (
            vm.provider_id == instance_id
            and vm.ip_private == ip_priv
            and (vm.ip_public == ip_pub if ip_pub else True)
        ):  # Already registered in CMDB
            logger.info(
                "Backing instance %s %s (%s / %s) found",
                vm.provider_id,
                vm.sku,
                vm.ip_public,
                vm.ip_private,
            )
            return False, str(vm.provider_id)
        logger.info("Backing instance found: %s", instance_id)
    else:
        logger.warning(
            "Detected a missing VM for instance '%s' in region %s",
            m.instance_name,
            m.region,
        )
        cmdb.mark_any_active_vms_as_deleted(m)

    resolved_instance_types = preprocess_ensure_vm_action(
        m, backing_instances[0] if backing_instances else None
    )

    short_lifetime_instance_types = (
        cmdb.get_short_lifetime_instance_types_with_zone_if_any(str(m.uuid))
    )
    if short_lifetime_instance_types:
        resolved_instance_types = apply_short_life_time_instances_reordering(
            resolved_instance_types,
            short_lifetime_instance_types,
            m.vm.instance_selection_strategy,
        )

    cloud_vm, created = ensure_spot_vm(
        m, resolved_instance_types, dry_run=dry_run
    )
    if dry_run:
        return False, "dummy"

    cmdb.finalize_ensure_vm(m, cloud_vm)

    return True if not backing_instances else False, cloud_vm.provider_id


def ensure_s3_backup_bucket(m: InstanceManifest):
    s3_try_create_bucket_if_not_exists(m.region, m.backup.s3_bucket)


def destroy_backups_if_any(m: InstanceManifest):
    s3_clean_bucket_path_if_exists(
        m.region, m.backup.s3_bucket, m.instance_name
    )


def destroy_instance(
    m: InstanceManifest,
) -> bool:  # TODO some duplication with --teardown-region
    logger.info(
        "Destroying cloud resources if any for instance %s ...",
        m.instance_name,
    )

    backing_instances = get_backing_vms_for_instances_if_any(
        m.region, m.instance_name
    )
    backing_ins_ids = [x["InstanceId"] for x in backing_instances]
    logger.info("Instances found for destroying: %s", backing_ins_ids)
    if backing_ins_ids and not dry_run:
        logger.info("Terminating instances %s ...", backing_ins_ids)
        terminate_instances_in_region(m.region, backing_ins_ids)

    vol_ids_and_sizes = get_operator_volumes_in_region(
        m.region, m.instance_name
    )
    logger.info("Volumes found: %s", vol_ids_and_sizes)
    if not dry_run and vol_ids_and_sizes:
        logger.info("OK. Sleeping 60s before deleting volumes ...")
        time.sleep(60)
        for vol_id, size in vol_ids_and_sizes:
            logger.info("Deleting VolumeId %s (%s GB) ...", vol_id, size)
            delete_volume_in_region(m.region, vol_id)

    logger.info("Looking for explicit NICs to delete ....")
    nic_ids = get_non_self_terminating_network_interfaces(
        m.region, m.instance_name
    )
    logger.info("NICs found: %s", nic_ids)
    if not dry_run and nic_ids:
        if not vol_ids_and_sizes:
            logger.info("OK. Sleeping 60s before deleting NICs ...")
            time.sleep(60)
        for nic_id in nic_ids:
            logger.info("Deleting NIC %s ...", nic_id)
            delete_network_interface(m.region, nic_id)

    logger.info("Looking for Elastic IPs to delete ....")
    eip_alloc_ids = get_addresses(m.region, m.instance_name)
    logger.info("Elastic IP Addresses found: %s", eip_alloc_ids)
    if not dry_run and eip_alloc_ids:
        if nic_ids:
            logger.info("Sleeping 60s before deleting EIPs ...")
            time.sleep(60)
        for alloc_id in eip_alloc_ids:
            logger.info("Releasing Address with AllocationId %s ...", alloc_id)
            release_address_by_allocation_id_in_region(m.region, alloc_id)

    logger.info(
        "OK - cloud resources for instance %s cleaned-up", m.instance_name
    )

    if m.backup.destroy_backups and m.backup.s3_bucket:
        destroy_backups_if_any(m)

    cmdb.finalize_destroy_instance(m)
    cmdb.mark_manifest_snapshot_as_succeeded(m)

    return True


def teardown_region(
    region: str,
    aws_access_key_id: str = "",
    aws_secret_access_key: str = "",
    dry_run: bool = False,
) -> None:
    logger.info(
        "%s all operator tagged resources in region %s ...",
        "DRY-RUN LISTING" if dry_run else "DESTROYING",
        region,
    )
    if not dry_run:
        logger.info("Sleep 5 ...")
        time.sleep(5)

    if aws_access_key_id and aws_secret_access_key:
        aws_client.AWS_ACCESS_KEY_ID = aws_access_key_id
        aws_client.AWS_SECRET_ACCESS_KEY = aws_secret_access_key

    for i in range(1, 4):
        logger.info("Try %s of max 3", i)
        try:

            logger.info("Looking for EC2 instances to delete ...")
            ins_ids = get_all_active_operator_instances_in_region(region)
            logger.info("Instances found for delete: %s", ins_ids)
            if not dry_run and ins_ids:
                logger.info("Terminating instances %s ...", ins_ids)
                terminate_instances_in_region(region, ins_ids)
                if ins_ids:
                    logger.info("Sleeping 30s before deleting volumes ...")
                    time.sleep(30)

            logger.info("Looking for EBS Volumes to delete ....")
            vol_ids_and_sizes = get_operator_volumes_in_region(region)
            logger.info("Volumes found: %s", vol_ids_and_sizes)
            if not dry_run and vol_ids_and_sizes:
                for vol_id, size in vol_ids_and_sizes:
                    logger.info(
                        "Deleting VolumeId %s (%s GB) ...", vol_id, size
                    )
                    delete_volume_in_region(region, vol_id)

            logger.info("Looking for explicit NICs to delete ....")
            nic_ids = get_non_self_terminating_network_interfaces(region)
            logger.info("NICs found: %s", nic_ids)
            if not dry_run and nic_ids:
                for nic_id in nic_ids:
                    logger.info("Deleting NIC %s ...", nic_id)
                    delete_network_interface(region, nic_id)
            logger.info("Cleanup loop completed")

            logger.info("Looking for EIPs to delete ....")
            elastic_address_alloc_ids = get_addresses(region)
            logger.info(
                "Elastic Addresses found: %s", elastic_address_alloc_ids
            )
            if not dry_run and elastic_address_alloc_ids:
                if nic_ids:
                    logger.info("Sleeping 60s before deleting EIPs ...")
                    time.sleep(60)
                for alloc_id in elastic_address_alloc_ids:
                    logger.info(
                        "Releasing Elastic Address with AllocationId %s ...",
                        alloc_id,
                    )
                    release_address_by_allocation_id_in_region(
                        region, alloc_id
                    )

            if not dry_run:
                try:
                    cmdb.finalize_destroy_region(region)
                except Exception:
                    logger.error("Could not mark instances as deleted in CMDB")
            break
        except Exception:
            logger.exception(f"Failed to complete cleanup loop {i}")
            logger.info("Sleep 60")
            time.sleep(60)


def have_main_hw_reqs_changed(
    m: InstanceManifest, prev_m: InstanceManifest
) -> bool:
    if (
        m.vm.cpu_min != prev_m.vm.cpu_min
        or m.vm.ram_min != prev_m.vm.ram_min
        or (
            m.vm.storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL
            and m.vm.storage_min > prev_m.vm.storage_min
        )
    ):
        return True
    return False


def check_for_explicit_tag_signalled_expiration_date(m) -> str:
    """Checks for user set SPOT_OPERATOR_EXPIRES_TAG on the instance directly
    to counter the "runaway daemon" problem (https://github.com/pg-spot-ops/pg-spot-operator/issues/33)
    """
    logger.debug(
        "Checking if %s tag set on the currently backing instance ...",
        SPOT_OPERATOR_EXPIRES_TAG,
    )
    backing_instances = get_backing_vms_for_instances_if_any(
        m.region, m.instance_name
    )
    if not backing_instances:
        return ""
    for instance in backing_instances:
        for tag in instance.get("Tags", []):
            if tag.get("Key") == SPOT_OPERATOR_EXPIRES_TAG:
                return tag["Value"]
    return ""


def do_main_loop(
    cli_dry_run: bool = False,
    cli_env_manifest: InstanceManifest | None = None,
    cli_user_manifest_path: str = "",
    cli_vault_password_file: str = "",
    cli_main_loop_interval_s: int = 60,
    cli_destroy_file_base_path: str = "",
    cli_teardown: bool = False,
    cli_connstr_output_only: bool = False,
    cli_connstr_format: str = "ssh",
    cli_ansible_path: str = "",
):
    global dry_run
    dry_run = cli_dry_run
    global default_vault_password_file
    default_vault_password_file = cli_vault_password_file
    if cli_ansible_path:
        global ansible_root_path
        ansible_root_path = cli_ansible_path

    first_loop = True
    loops = 0

    while True:
        loops += 1
        logger.debug("Starting main loop iteration %s ...", loops)
        loop_errors = False

        try:
            # Step 0 - load manifest from CLI args / full adhoc ENV manifest or manifest file
            m: InstanceManifest = None  # type: ignore
            if cli_env_manifest:
                (
                    logger.info(
                        "Processing manifest for instance '%s' set via CLI / ENV ...",
                        cli_env_manifest.instance_name,
                    )
                    if first_loop
                    else None
                )
                m = cli_env_manifest
            else:
                (
                    logger.info(
                        "Processing manifest from path %s...",
                        cli_user_manifest_path,
                    )
                    if first_loop
                    else None
                )
                if os.path.exists(os.path.expanduser(cli_user_manifest_path)):
                    with open(os.path.expanduser(cli_user_manifest_path)) as f:
                        m = manifests.try_load_manifest_from_string(f.read())  # type: ignore

            if not (m and m.instance_name):
                logger.info("No valid manifest found - nothing to do ...")
                raise NoOp()
            if m.is_paused:
                logger.info(
                    "Skipping instance %s as is_paused set", m.instance_name
                )
                raise NoOp()

            # Step 1 - register or update manifest in CMDB

            instance = cmdb.get_instance_by_name_cloud(m)
            m.fill_in_defaults()
            if not instance:
                m.uuid = cmdb.register_instance_or_get_uuid(m)
                if not m.is_expired():
                    try_rm_file_if_exists(
                        cli_destroy_file_base_path + m.instance_name
                    )
                logger.info(
                    "Instance destroy signal file path: %s",
                    cli_destroy_file_base_path + m.instance_name,
                )
            else:
                m.uuid = instance.uuid  # type: ignore
            m.session_vars["uuid"] = m.uuid

            if not m.manifest_snapshot_id:
                m.manifest_snapshot_id = (
                    cmdb.store_manifest_snapshot_if_changed(m)
                )

            if not (m and m.uuid and m.manifest_snapshot_id):
                logger.error(
                    "Failed to register instance '%s' (%s) to CMDB, skipping ...",
                    m.instance_name,
                    m.cloud,
                )
                raise NoOp()

            # Step 2 - detect if something needs to be done based on manifest

            # Set AWS creds
            m.decrypt_secrets_if_any()
            set_access_keys(
                m.aws.access_key_id,
                m.aws.secret_access_key,
                m.aws.profile_name,
            )

            logger.debug(
                "Processing instance '%s' (%s) ...",
                m.instance_name,
                m.cloud,
            )
            if first_loop:
                logger.debug("Manifest: %s", "\n" + m.original_manifest)

            prev_success_manifest = cmdb.get_last_successful_manifest_if_any(
                m.uuid
            )
            current_manifest_applied_successfully = (
                True
                if prev_success_manifest
                and prev_success_manifest.manifest_snapshot_id
                == m.manifest_snapshot_id
                else False
            )

            shut_down_after_destroy = cli_teardown
            destroyed = False
            if os.path.exists(cli_destroy_file_base_path + m.instance_name):
                m.expiration_date = "now"
                shut_down_after_destroy = True

            if (
                not m.expiration_date
                and prev_success_manifest
                and not prev_success_manifest.expiration_date
                and not m.vm.host
            ):
                # Check for user signalled expiry via manual tag setting on the VM
                tag_signalled_expiration_date = (
                    check_for_explicit_tag_signalled_expiration_date(m)
                )
                if tag_signalled_expiration_date:
                    logger.warning(
                        "Detected a user tag (%s) signalled expiry: %s",
                        SPOT_OPERATOR_EXPIRES_TAG,
                        tag_signalled_expiration_date,
                    )
                    m.expiration_date = tag_signalled_expiration_date
                    if not cli_dry_run:
                        cmdb.add_instance_to_ignore_list(
                            m.instance_name
                        )  # To make sure externally signalled instance doesn't get resurrected on this engine node")

            if not instance and m.is_expired():
                if first_loop and not current_manifest_applied_successfully:
                    destroyed = destroy_instance(m)
                else:
                    logger.debug(
                        "Instance '%s' expired, NoOp",
                        m.instance_name,
                    )

            if m.is_expired() and (not prev_success_manifest or not prev_success_manifest.is_expired()):  # type: ignore
                destroyed = destroy_instance(m)
            if destroyed and shut_down_after_destroy:
                logger.info(
                    "Shutting down after successful destroy as destroy file / teardown flag set"
                )
                try_rm_file_if_exists(
                    cli_destroy_file_base_path + m.instance_name
                )
                exit(0)

            if prev_success_manifest:
                main_hw_reqs_changed = have_main_hw_reqs_changed(
                    m, prev_success_manifest
                )
                if main_hw_reqs_changed:
                    backing_instances = get_backing_vms_for_instances_if_any(
                        m.region, m.instance_name
                    )
                    backing_ins_ids = [
                        x["InstanceId"] for x in backing_instances
                    ]
                    if backing_ins_ids:
                        if dry_run:
                            logger.warning(
                                "Would terminate current VMs %s as HW reqs have changed!",
                                backing_ins_ids,
                            )
                        else:
                            logger.warning(
                                "Terminating current VMs (%s) as HW reqs have changed ...",
                                backing_ins_ids,
                            )
                            terminate_instances_in_region(
                                m.region, backing_ins_ids
                            )
                            logger.info("OK - terminated. Sleeping 5s ...")
                            time.sleep(
                                5
                            )  # As get_backing_vms_for_instances_if_any cached for 5s
                    else:
                        logger.debug(
                            "HW reqs change detected but no backing VM found"
                        )

            if m.is_expired() or cmdb.is_instance_ignore_listed(
                m.instance_name
            ):
                logger.debug("Instance expired or ignore-listed, skipping")
                raise NoOp()

            if m.backup.type == BACKUP_TYPE_PGBACKREST and not cli_dry_run:
                ensure_s3_backup_bucket(m)

            vm_created_recreated = False
            if m.vm.host and m.vm.login_user:
                logger.info(
                    "Using user provided VM address / user for Ansible setup: %s@%s",
                    m.vm.login_user,
                    m.vm.host,
                )
                if cli_dry_run:
                    ssh_ok = check_ssh_ping_ok(
                        m.vm.login_user, m.vm.host, m.ansible.private_key
                    )
                    if not ssh_ok:
                        raise Exception("Could not SSH connect to --vm-host")
                    logger.info("SSH connect OK")
            else:
                vm_created_recreated, vm_provider_id = ensure_vm(m)
                if vm_created_recreated:
                    logger.info(
                        "Sleeping 10s as VM %s created, give time to boot",
                        vm_provider_id,
                    )
                    time.sleep(10)

            diff = m.diff_manifests(
                prev_success_manifest, original_manifests_only=True
            )

            if (
                vm_created_recreated
                or diff
                or not current_manifest_applied_successfully
            ):
                # Just reconfigure the VM if any changes discovered, relying on Ansible idempotence
                if diff:
                    logging.info("Detected manifest changes: %s", diff)

                if m.vm_only:
                    logger.info("Skipping Postgres setup as vm_only set")
                    logger.info(
                        "*** SSH connect string *** - '%s'", get_ssh_connstr(m)
                    )
                    cmdb.mark_manifest_snapshot_as_succeeded(m)
                else:
                    run_action(constants.ACTION_INSTANCE_SETUP, m)

            else:
                logger.info(
                    "No state changes detected for instance '%s'",
                    m.instance_name,
                )
                raise NoOp()

            logger.debug(
                "Finished processing instance %s (%s)",
                m.instance_name,
                m.cloud,
            )

        except (KeyboardInterrupt, SystemExit):
            exit(1)
        except NoOp:
            logger.debug("NoOp")
        except UserExit:
            logger.info("User exit")
            exit(0)
        except Exception:
            logger.exception("Exception on main loop")
            loop_errors = True

        if cli_connstr_output_only and not loop_errors:
            logger.info(
                "Outputting the %s connect string to stdout and exiting.",
                cli_connstr_format if m.vm_only else "libpq",
            )
            if m.vm_only:
                print(get_ssh_connstr(m, cli_connstr_format))
            else:
                print(get_instance_connect_string(m))
            exit(0)

        first_loop = False
        if cli_dry_run:
            logger.info("Exiting due to --dry-run")
            exit(0)
        logger.info(
            "Main loop finished. Sleeping for %s s ...",
            cli_main_loop_interval_s,
        )
        time.sleep(cli_main_loop_interval_s)
