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
    write_to_s3_bucket,
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
from pg_spot_operator.cmdb import (
    Instance,
    get_instance_connect_string,
    get_instance_connect_string_postgres,
    get_latest_vm_by_uuid,
    get_ssh_connstr,
)
from pg_spot_operator.constants import (
    ACTION_INSTANCE_SETUP,
    BACKUP_TYPE_PGBACKREST,
    DEFAULT_CONFIG_DIR,
    DEFAULT_INSTANCE_SELECTION_STRATEGY,
    MF_SEC_VM_STORAGE_TYPE_LOCAL,
    SPOT_OPERATOR_EXPIRES_TAG,
)
from pg_spot_operator.instance_type_selection import InstanceTypeSelection
from pg_spot_operator.manifests import InstanceManifest
from pg_spot_operator.pgtuner import TuningInput, apply_postgres_tuning
from pg_spot_operator.util import (
    check_setup_completed_marker_file_exists,
    check_ssh_ping_ok,
    merge_action_output_params,
    merge_user_and_tuned_non_conflicting_config_params,
    space_pad_manifest,
    try_rm_file_if_exists,
)

MAX_PARALLEL_ACTIONS = 2
ACTION_MAX_DURATION_S = 600
CALLBACK_MAX_DURATION_S = 30
VM_KEEPALIVE_SCANNER_INTERVAL_S = 60
ACTION_HANDLER_TEMP_SPACE_ROOT = "~/.pg-spot-operator/tmp"
ANSIBLE_DEFAULT_ROOT_PATH = "~/.pg-spot-operator/ansible"

logger = logging.getLogger(__name__)

default_vault_password_file: str = ""
dry_run: bool = False
debug: bool = False
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

    handler_dir_to_fork = os.path.join(
        "./ansible", manifest.api_version
    )  # Dev mode
    if os.path.exists(os.path.expanduser(ansible_root_path)):
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
            [executable_full_path, str(ACTION_MAX_DURATION_S)],
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=temp_workdir,
            text=True,
        )
        stdout, _ = p.communicate(timeout=ACTION_MAX_DURATION_S)
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
            "Handler at %s failed with exit code %s",
            executable_full_path,
            p.returncode,
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


def os_execute_setup_finished_callback_vm_only(
    executable_full_path: str,
    connstr_format: str,
    m: InstanceManifest,
) -> None:
    """For --vm-only mode using VM ssh / ansible connstr
    - timeout
    - "30"
    - "{{ setup_finished_callback }}"
    - "{{ instance_name }}"
    - "{{ connstr_private }}"
    - "{{ connstr_public }}"
    - "{{ user_tags }}"
    """
    p: subprocess.Popen = None  # type: ignore
    stdout = None

    try:
        logging.debug("Starting callback handler at %s", executable_full_path)
        vm = get_latest_vm_by_uuid(m.uuid)
        if not vm:
            raise Exception(
                f"Failed to determine VM IP addresses for instance {m.instance_name}"
            )
        p = subprocess.Popen(
            [
                "timeout",
                str(CALLBACK_MAX_DURATION_S),
                executable_full_path,
                m.instance_name,
                str(vm.ip_private),
                str(vm.ip_public),
                get_ssh_connstr(m, connstr_format),
                json.dumps(m.user_tags),
            ],
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        stdout, _ = p.communicate(timeout=CALLBACK_MAX_DURATION_S + 1)
        logging.info("Callback handler succeeded")
    except subprocess.TimeoutExpired:
        logging.error(
            "Callback handler %s ran over max duration, terminating the process ...",
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


def get_tuning_inputs_from_manifest_hw_reqs(
    m: InstanceManifest,
) -> TuningInput:
    """Convert manifest HW reqs for tuning
    We assume a 1-to-4 CPU-to-RAM ration if either specified and no exact instance info
    """
    # Start with HW min reqs from user, refine later if have actual resolved instance type infos
    cpus = m.vm.cpu_min
    if not cpus and m.vm.ram_min:
        cpus = math.ceil(m.vm.ram_min / 4)
    ram_gb = m.vm.ram_min
    if not ram_gb and m.vm.cpu_min:
        ram_gb = m.vm.cpu_min * 4
    return TuningInput(
        postgres_version=m.postgres.version,
        ram_mb=(ram_gb or 1) * 1024,
        cpus=(cpus or 2),
        storage_type=m.vm.storage_type,
        storage_speed_class=m.vm.storage_speed_class,
    )


def get_tuning_inputs_from_real_instance_info_if_present(
    m: InstanceManifest,
) -> TuningInput | None:
    """Provide actual HW specs for tuning if available"""
    ins_type_info: InstanceTypeInfo | None = None

    try:
        backing_instances = get_backing_vms_for_instances_if_any(
            m.region, m.instance_name
        )
        if backing_instances:
            ins_type_info = resolve_instance_type_info(
                backing_instances[0]["InstanceType"], m.region
            )
            if ins_type_info:
                return TuningInput(
                    postgres_version=m.postgres.version,
                    ram_mb=ins_type_info.ram_mb,
                    cpus=ins_type_info.cpu,
                    storage_type=m.vm.storage_type,
                    storage_speed_class=ins_type_info.storage_speed_class,
                )
        if (
            m.vm.instance_types
        ):  # If user has specified an explicit list of instance types, pick the first
            try:
                ins_type_info = resolve_instance_type_info(
                    m.vm.instance_types[0], m.region
                )
            except Exception:
                logger.error(
                    "Failed to fetch actual HW details, tuning Postgres based on user HW reqs"
                )
            if ins_type_info:
                return TuningInput(
                    postgres_version=m.postgres.version,
                    ram_mb=ins_type_info.ram_mb,
                    cpus=ins_type_info.cpu,
                    storage_type=m.vm.storage_type,
                    storage_speed_class=ins_type_info.storage_speed_class,
                )
    except Exception:
        logger.error(
            "Failed to fetch actual HW details, tuning Postgres based on user HW reqs"
        )
    return None


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

        try:
            tuning_input = get_tuning_inputs_from_manifest_hw_reqs(m)
            tuning_input_exact = (
                get_tuning_inputs_from_real_instance_info_if_present(m)
            )
            if tuning_input_exact:
                tuning_input = tuning_input_exact

            if not tuning_input:
                raise Exception("Can't apply tuning - no HW information")

            tuned_config_params = apply_postgres_tuning(
                tuning_input, m.postgres.tuning_profile.strip().lower()
            )

            logger.info(
                "%s tuned config parameters will be added to postgresql.conf",
                len(tuned_config_params),
            )
            logger.debug("Tuned config params: %s", tuned_config_params)
            merged_config_lines = (
                merge_user_and_tuned_non_conflicting_config_params(
                    tuned_config_params,
                    m.postgres.config_lines.copy(),
                )
            )
            if merged_config_lines:
                if "postgres" not in m.session_vars:
                    m.session_vars["postgres"] = {}
                m.session_vars["postgres"][
                    "config_lines"
                ] = merged_config_lines
        except Exception:  # Tuning not a showstopper
            logger.warning(
                "Failed to apply tuning profile %s to instance %s",
                m.postgres.tuning_profile,
                m.instance_name,
            )


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
    logger.debug("SSH connect string: %s", get_ssh_connstr(m))

    rc, outputs = run_ansible_handler(
        action, temp_workdir, executable_full_path, m
    )

    if rc == 0:
        logger.info("OK action %s completed", action)
        if action == ACTION_INSTANCE_SETUP:
            display_connect_strings(m)

        if not debug:
            clean_up_old_logs_if_any(
                old_threshold_days=0
            )  # To avoid possibility of unencrypted secrets hanging around for too long
        return rc == 0, outputs

    raise Exception("Ansible setup failed")


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


def ensure_vm(m: InstanceManifest) -> tuple[bool, str, str]:
    """Make sure we have a VM
    Returns True if a VM was created / recreated + Provider ID + primary connect IP
    """
    logger.debug(
        "Ensuring instance %s (%s) %s has a backing VM ...",
        m.instance_name,
        m.cloud,
        m.uuid,
    )

    vm = cmdb.get_latest_vm_by_uuid(m.uuid)
    if (
        vm and not vm.deleted_on and vm.provider_id
    ):  # 1st let's try the cheaper SSH check
        try:
            ssh_ok = check_ssh_ping_ok(
                str(vm.login_user),
                str(vm.ip_public or vm.ip_private),
                max_wait_seconds=2,
            )
            if ssh_ok:
                logger.info(
                    "Backing instance %s %s (%s / %s) found",
                    vm.provider_id,
                    vm.sku,
                    vm.ip_public,
                    vm.ip_private,
                )
                return (
                    False,
                    str(vm.provider_id),
                    str(vm.ip_public or vm.ip_private),
                )
        except Exception:
            logger.warning(
                "Failed to SSH check instance %s, following up with an API check",
                vm.provider_id,
            )

    # Check if VM there via AWS API call
    backing_instances = get_backing_vms_for_instances_if_any(
        m.region, m.instance_name
    )
    if backing_instances:
        if len(backing_instances) > 1:
            raise Exception(
                f"A single backing instance expected - got: {backing_instances}"
            )  # TODO take latest by creation date
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
            return False, str(vm.provider_id), ip_pub or ip_priv
        logger.info("Backing instance found: %s", instance_id)
    else:
        logger.warning(
            "Detected a missing VM for instance '%s' in region %s",
            m.instance_name,
            m.region,
        )
        cmdb.mark_any_active_vms_as_deleted(str(m.uuid))

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
        return False, "dummy", "dummy_ip"

    if cloud_vm:
        cmdb.finalize_ensure_vm(m, cloud_vm)

    return (
        created,
        cloud_vm.provider_id if cloud_vm else "",
        cloud_vm.ip_public or cloud_vm.ip_private if cloud_vm else "",
    )


def ensure_s3_backup_bucket(m: InstanceManifest):
    s3_try_create_bucket_if_not_exists(m.region, m.backup.s3_bucket)


def destroy_backups_if_any(m: InstanceManifest):
    s3_clean_bucket_path_if_exists(
        m.region, m.backup.s3_bucket, m.instance_name
    )


def destroy_instance(
    m: InstanceManifest,
) -> bool:  # TODO some duplication with --teardown-region
    if m.region == "auto":
        ins = cmdb.get_instance_by_name(m.instance_name)
        if not ins or ins.region == "auto":
            logger.error(
                "Can't determine instance region for teardown. Specify via --region"
            )
            exit(1)
        m.region = ins.region

    logger.info(
        "Destroying cloud resources if any for instance %s ...",
        m.instance_name,
    )

    backing_instances = get_backing_vms_for_instances_if_any(
        m.region, m.instance_name
    )
    backing_ins_ids = [x["InstanceId"] for x in backing_instances]
    logger.info(
        "Instances found for destroying in region %s: %s",
        m.region,
        backing_ins_ids,
    )
    if backing_ins_ids and not dry_run:
        logger.info(
            "Terminating instances %s in region %s ...",
            backing_ins_ids,
            m.region,
        )
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

    # TODO Explicit NICs now not created anymore, can remove after some time
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
        logger.info("Sleeping 10s before deleting EIPs ...")
        time.sleep(10)
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


def does_instance_type_fit_manifest_hw_reqs(
    m: InstanceManifest, iti: InstanceTypeInfo
) -> bool:
    if m.vm.cpu_min and iti.cpu < m.vm.cpu_min:
        logger.debug("instance cpu_min not fitting hw reqs")
        return False
    if m.vm.cpu_max and iti.cpu > m.vm.cpu_max:
        logger.debug("instance cpu_max not fitting hw reqs")
        return False
    if m.vm.ram_min and (iti.ram_mb / 1000) < m.vm.ram_min:
        logger.debug("instance ram_min not fitting hw reqs")
        return False
    if m.vm.ram_max and (iti.ram_mb / 1000) > m.vm.ram_max:
        logger.debug("instance ram_max not fitting hw reqs")
        return False
    if (
        m.vm.storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL
        and m.vm.storage_min > iti.instance_storage
    ):
        logger.debug("instance instance_storage not fitting hw reqs")
        return False
    return True


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


def write_connstr_to_s3_if_bucket_set(m: InstanceManifest) -> None:
    """Failures considered non-critical, as the service running itself.
    If some bucket address params missing, we try to put together a valid bucket url.
    Bucket writing format:
    {
        "connstr": "postgresql://app1:secret@1.2.3.4:5432/postgres?sslmode=require",
        "instance_name": "",
        "ip_public": "",
        "ip_private": "1.2.3.4",
        "admin_user": "app1",
        "admin_password": "secret",
        "app_db_name": "postgres"
    }
    """
    if not m.integrations.connstr_bucket:
        return
    if (
        m.integrations.connstr_bucket
        and not m.integrations.connstr_bucket_filename
    ):
        logger.warning(
            "--connstr-bucket-filename not set, can't store connstr to s3"
        )
        return
    try:
        connstr = get_instance_connect_string_postgres(m)
        if not connstr:
            logger.error("No valid connect string found for bucket writing")
            return

        vm = get_latest_vm_by_uuid(m.uuid)

        connect_data = {
            "connstr": connstr,
            "instance_name": m.instance_name,
            "ip_public": vm.ip_public if vm and vm.ip_public else "",
            "ip_private": vm.ip_private if vm and vm.ip_private else "",
            "admin_user": m.postgres.admin_user,
            "admin_password": m.postgres.admin_password,
            "app_db_name": m.postgres.app_db_name or "postgres",
        }
        write_to_s3_bucket(
            data=json.dumps(connect_data),
            region=(m.integrations.connstr_bucket_region or m.region),
            bucket_name=m.integrations.connstr_bucket,
            bucket_key=m.integrations.connstr_bucket_filename,
            endpoint=m.integrations.connstr_bucket_endpoint,
            access_key=(
                m.integrations.connstr_bucket_key or m.aws.access_key_id
            ),
            access_secret=(
                m.integrations.connstr_bucket_secret or m.aws.secret_access_key
            ),
        )
        logger.info(
            "Connect information successfully written to bucket %s, key %s",
            m.integrations.connstr_bucket,
            m.integrations.connstr_bucket_filename,
        )
    except Exception:
        logger.exception(
            "Failed to write the connect string to specified bucket"
        )
        return


def write_connstr_to_output_path(
    connstr_output_path: str, connstr: str
) -> None:
    """Non-critical"""
    try:
        current_file_contents = ""
        if os.path.exists(os.path.expanduser(connstr_output_path)):
            with open(os.path.expanduser(connstr_output_path)) as f:
                current_file_contents = f.read()
        if current_file_contents and current_file_contents == connstr:
            logger.debug(
                "Not updating the --connstr-output-path as no changes"
            )
            return
        with open(connstr_output_path, "w") as f:
            f.write(connstr)
    except Exception as e:
        logger.error(
            "Failed to output connstr to %s: Error: %s", connstr_output_path, e
        )


def get_manifest_from_cli_input(
    cli_env_manifest, cli_user_manifest_path, first_loop
) -> InstanceManifest:
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
        logger.info("Skipping instance %s as is_paused set", m.instance_name)
        raise NoOp()
    return m


def register_or_update_manifest_in_cmdb(
    cli_destroy_file_base_path, m
) -> Instance | None:
    instance = cmdb.get_instance_by_name(m.instance_name)

    if not instance:
        m.uuid = cmdb.register_instance_or_get_uuid(m)
        if not m.is_expired():
            try_rm_file_if_exists(cli_destroy_file_base_path + m.instance_name)
        logger.debug(
            "Instance destroy signal file path: %s",
            cli_destroy_file_base_path + m.instance_name,
        )
    else:
        m.uuid = instance.uuid  # type: ignore
        cmdb.update_instance_if_main_data_changed(m)

    m.session_vars["uuid"] = m.uuid
    if not m.manifest_snapshot_id:
        m.manifest_snapshot_id = cmdb.store_manifest_snapshot_if_changed(m)

    if not (m and m.uuid and m.manifest_snapshot_id):
        logger.error(
            "Failed to register instance '%s' (%s) to CMDB, skipping ...",
            m.instance_name,
            m.cloud,
        )
        raise NoOp()

    return instance


def decrypt_and_set_aws_secrets_if_any(m):
    # Set AWS creds
    m.decrypt_secrets_if_any()
    set_access_keys(
        m.aws.access_key_id,
        m.aws.secret_access_key,
        m.aws.profile_name,
    )


def stop_running_vms_if_any(instance_name: str, dry_run: bool = False) -> None:
    ins = cmdb.get_instance_by_name(instance_name)
    if not ins:
        logger.error(
            "Instance %s not found from CMDB, can't determine the region for VM deletion",
            instance_name,
        )
        return

    backing_instances = get_backing_vms_for_instances_if_any(
        ins.region, instance_name
    )
    backing_ins_ids = [x["InstanceId"] for x in backing_instances]
    if backing_ins_ids:
        if dry_run:
            logger.warning(
                "Would terminate current VMs in region %s: %s",
                ins.region,
                backing_ins_ids,
            )
        else:
            logger.warning(
                "Terminating current VMs in region %s: %s ...",
                ins.region,
                backing_ins_ids,
            )
            terminate_instances_in_region(ins.region, backing_ins_ids)
            logger.info("OK - instances terminated due to --stop command")
            cmdb.mark_instance_as_stopped_by_name(instance_name)
            cmdb.mark_any_active_vms_as_deleted(str(ins.uuid))
            logger.debug("CMDB status updated")


def drop_old_instance_if_main_hw_reqs_changed(
    m: InstanceManifest,
    dry_run: bool = False,
) -> bool:
    """Returns true if upscale needed / done"""
    backing_instances = get_backing_vms_for_instances_if_any(
        m.region, m.instance_name
    )
    if not backing_instances:
        return False

    backing_ins_id = backing_instances[0]["InstanceId"]
    iti = resolve_instance_type_info(
        backing_instances[0]["InstanceType"], m.region
    )

    hw_change_needed = does_instance_type_fit_manifest_hw_reqs(m, iti)
    if hw_change_needed:
        return False

    if dry_run:
        logger.warning(
            "Would terminate current VMs %s as HW reqs have changed!",
            backing_ins_id,
        )
    else:
        logger.warning(
            "Terminating current VM %s as HW reqs have changed ...",
            backing_ins_id,
        )
        terminate_instances_in_region(m.region, [backing_ins_id])
        logger.info("OK - terminated. Sleeping 5s ...")
        time.sleep(5)  # As get_backing_vms_for_instances_if_any cached for 5s

    return True


def do_main_loop(
    cli_dry_run: bool = False,
    cli_debug: bool = False,
    cli_env_manifest: InstanceManifest | None = None,
    cli_user_manifest_path: str = "",
    cli_vault_password_file: str = "",
    cli_main_loop_interval_s: int = 60,
    cli_destroy_file_base_path: str = "",
    cli_resume: bool = False,
    cli_teardown: bool = False,
    cli_connstr_only: bool = False,
    cli_connstr_format: str = "ssh",
    cli_ansible_path: str = "",
    cli_connstr_output_path: str = "",
):
    global dry_run
    dry_run = cli_dry_run
    global debug
    debug = cli_debug
    global default_vault_password_file
    default_vault_password_file = cli_vault_password_file
    if cli_ansible_path:
        global ansible_root_path
        ansible_root_path = cli_ansible_path

    first_loop = True
    loops = 0
    start_time = time.time()

    while True:
        loops += 1
        logger.debug("Starting main loop iteration %s ...", loops)
        loop_errors = False

        if cli_connstr_only and time.time() - start_time > 1800:
            logger.error("Failed to provision a VM in 30min, aborting")
            exit(2)

        try:
            # Step 0 - load manifest from CLI args / full adhoc ENV manifest or manifest file
            m: InstanceManifest = get_manifest_from_cli_input(
                cli_env_manifest, cli_user_manifest_path, first_loop
            )
            if cli_resume:
                ins = cmdb.get_instance_by_name(m.instance_name)
                if not ins:
                    logger.error(
                        "Instance %s not found from CMDB, can't resume instance. Remove the --resume flag and retry",
                        m.instance_name,
                    )
                    exit(1)
                m = cmdb.get_last_successful_manifest_if_any(  # type: ignore
                    ins.uuid, use_last_manifest=True
                )
                if not m:
                    logger.error(
                        "No previous manifest found to --resume instance %s, can't proceed",
                        m.instance_name,
                    )
                    exit(1)
                (
                    logger.info(
                        "Resuming instance %s in region %s...",
                        m.instance_name,
                        m.region,
                    )
                    if cli_resume and first_loop
                    else None
                )

            # Step 1 - register or update manifest snapshot in CMDB
            m.fill_in_defaults()
            instance: Instance | None = register_or_update_manifest_in_cmdb(
                cli_destroy_file_base_path, m
            )

            # Step 2 - detect if something needs to be done based on manifest

            decrypt_and_set_aws_secrets_if_any(m)

            logger.debug(
                "Processing instance '%s' (%s) ...",
                m.instance_name,
                m.cloud,
            )
            if first_loop and debug:
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
                raise UserExit()

            if (
                prev_success_manifest
            ):  # HW reqs might have changed so that need to
                drop_old_instance_if_main_hw_reqs_changed(m, dry_run)

            if m.is_expired() or cmdb.is_instance_ignore_listed(
                m.instance_name
            ):
                logger.debug("Instance expired or ignore-listed, skipping")
                raise NoOp()

            if m.backup.type == BACKUP_TYPE_PGBACKREST and not cli_dry_run:
                ensure_s3_backup_bucket(m)

            vm_created_recreated = False
            vm_ip: str = ""
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
                vm_created_recreated, vm_provider_id, vm_ip = ensure_vm(m)
                if vm_created_recreated and not m.vm_only and not cli_dry_run:
                    # Wait until SSH reachable so that first Ansible Postgres loop succeeds
                    check_ssh_ping_ok(
                        m.vm.login_user,
                        vm_ip,
                        m.ansible.private_key,
                        max_wait_seconds=30,
                    )
            if not vm_created_recreated or m.vm.host:
                if not check_setup_completed_marker_file_exists(
                    vm_ip or m.vm.host, m.vm.login_user, m.ansible.private_key
                ):
                    vm_created_recreated = (
                        True  # Re-run setup if marker file not there / deleted
                    )

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
                    logging.info(
                        "Detected manifest changes in keys: %s",
                        (
                            diff
                            if debug
                            else list(diff.get("values_changed", {}).keys())
                        ),
                    )

                if m.vm_only:
                    if (
                        m.vm.storage_min != -1 and not m.no_mount_disks
                    ):  # -1 denotes EBS OS disk only
                        run_action(constants.ACTION_MOUNT_DISKS, m)
                    logger.info("Skipping Postgres setup as vm_only set")
                    logger.info(
                        "*** SSH connect string *** - '%s'", get_ssh_connstr(m)
                    )
                    if (
                        m.integrations.setup_finished_callback
                    ):  # Run the callback still if set
                        if os.path.exists(
                            os.path.expanduser(
                                m.integrations.setup_finished_callback
                            )
                        ):
                            os_execute_setup_finished_callback_vm_only(
                                m.integrations.setup_finished_callback,
                                cli_connstr_format,
                                m,
                            )
                        else:
                            logger.warning(
                                "Setup finished callback not found at %s",
                                m.integrations.setup_finished_callback,
                            )

                    cmdb.mark_manifest_snapshot_as_succeeded(m)
                else:
                    run_action(constants.ACTION_INSTANCE_SETUP, m)

                    write_connstr_to_s3_if_bucket_set(m)

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

        if cli_dry_run:
            logger.info("Exiting due to --dry-run")
            exit(0)

        if cli_connstr_output_path and not loop_errors:
            logger.info(
                "Outputting the connect string (--connstr-format=%s) to %s ...",
                cli_connstr_format,
                cli_connstr_output_path,
            )
            write_connstr_to_output_path(
                cli_connstr_output_path,
                get_instance_connect_string(m, cli_connstr_format),
            )

        if cli_connstr_only and not loop_errors:
            logger.info(
                "Outputting the connect string (--connstr-format=%s) to stdout and exiting ...",
                cli_connstr_format,
            )
            print(get_instance_connect_string(m, cli_connstr_format))
            exit(0)

        first_loop = False

        logger.info(
            "Main loop finished. Sleeping for %s s ...",
            cli_main_loop_interval_s,
        )
        time.sleep(cli_main_loop_interval_s)
