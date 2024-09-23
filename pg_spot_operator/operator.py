import json
import logging
import os
import shutil
import signal
import stat
import subprocess
import time
from datetime import datetime

import yaml

from pg_spot_operator import cloud_api, cmdb, constants, manifests
from pg_spot_operator.cloud_impl import aws_client
from pg_spot_operator.cloud_impl.aws_spot import (
    describe_instance_type,
    get_current_spot_price,
)
from pg_spot_operator.cloud_impl.aws_vm import ensure_spot_vm
from pg_spot_operator.cloud_impl.cloud_structs import ResolvedInstanceTypeInfo
from pg_spot_operator.cloud_impl.cloud_util import (
    extract_cpu_arch_from_sku_desc,
)
from pg_spot_operator.constants import CLOUD_AWS
from pg_spot_operator.manifests import InstanceManifest
from pg_spot_operator.util import (
    merge_action_output_params,
    merge_user_and_tuned_non_conflicting_config_params,
    run_process_with_output,
)

MAX_PARALLEL_ACTIONS = 2
ACTION_MAX_DURATION = 600
VM_KEEPALIVE_SCANNER_INTERVAL_S = 60
ACTION_HANDLER_TEMP_SPACE_ROOT = "~/.pg-spot-operator/tmp"
ANSIBLE_ROOT = "./ansible"

logger = logging.getLogger(__name__)

default_vault_password_file: str = ""
dry_run: bool = False
operator_startup_time = time.time()


class NoOp(Exception):
    pass


class UserExit(Exception):
    pass


def preprocess_ensure_vm_action(
    m: InstanceManifest,
) -> ResolvedInstanceTypeInfo:
    """Fill in the "blanks" that are not set by the user but still needed, like the SKU"""

    sku: ResolvedInstanceTypeInfo
    if not m.vm.instance_type:
        cheapest_skus = cloud_api.get_cheapest_skus_for_hardware_requirements(
            m
        )
        if not cheapest_skus:
            raise Exception(
                f"No SKUs matching HW requirements found for instance {m.instance_name} in {m.cloud} region {m.region}"
            )
        sku = cheapest_skus[0]  # TODO implement multi-sku
        m.vm.instance_type = sku.instance_type
    else:
        i_desc = describe_instance_type(m.vm.instance_type, m.region)
        sku = ResolvedInstanceTypeInfo(
            instance_type=m.vm.instance_type,
            cloud=CLOUD_AWS,
            region=m.region,
            arch=extract_cpu_arch_from_sku_desc(CLOUD_AWS, i_desc),
            provider_description=i_desc,
            availability_zone=m.availability_zone,
            cpu=i_desc.get("VCpuInfo", {}).get("DefaultVCpus", 0),
            ram=int(i_desc.get("MemoryInfo", {}).get("SizeInMiB", 0) / 1024),
            instance_storage=i_desc.get("InstanceStorageInfo", {}).get(
                "TotalSizeInGB", 0
            ),
        )
    m.vm.cpu_architecture = sku.arch

    logger.info(
        "SKU %s main specs - vCPU: %s, RAM: %s, instance storage: %s",
        sku.instance_type,
        sku.cpu,
        sku.ram,
        sku.instance_storage,
    )

    if not sku.monthly_spot_price:
        sku.monthly_spot_price = (
            get_current_spot_price(
                m.region, m.vm.instance_type, m.availability_zone
            )
            * 24
            * 30
        )
    logger.info(
        "Selected SKU %s (%s) in %s region %s for a monthly Spot price of $%s",
        sku.instance_type,
        sku.arch,
        sku.cloud,
        sku.region,
        sku.monthly_spot_price,
    )
    if not sku.monthly_ondemand_price:
        sku.monthly_ondemand_price = (
            cloud_api.try_get_monthly_ondemand_price_for_sku(
                m.cloud, m.region, sku.instance_type
            )
        )

    if sku.monthly_ondemand_price and sku.monthly_spot_price:
        spot_discount = (
            100.0
            * (sku.monthly_spot_price - sku.monthly_ondemand_price)
            / sku.monthly_ondemand_price
        )
        logger.info(
            "Spot discount rate for SKU %s in region %s = %s%% (spot $%s vs on-demand $%s)",
            sku.instance_type,
            m.region,
            round(spot_discount, 1),
            sku.monthly_spot_price,
            sku.monthly_ondemand_price,
        )

    return sku


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def get_ansible_inventory_file_str_for_action(
    action: str, uuid: str, instance_name: str
) -> str:
    groups: dict = {"all": {"hosts": {}}}
    logging.debug(
        "Putting together required inventory for action %s of %s ...",
        action,
        instance_name,
    )
    if action in [
        constants.ACTION_ENSURE_VM,
        constants.ACTION_TERMINATE_VM,
        constants.ACTION_DESTROY_INSTANCE,
        constants.ACTION_DESTROY_BACKUPS,
    ]:
        groups["all"]["hosts"]["localhost"] = {}
        return yaml.dump(groups, Dumper=NoAliasDumper)

    vm = cmdb.get_latest_vm_by_uuid(uuid)
    if not vm:
        raise Exception(
            f"No active VM found for instance {instance_name} UUID {uuid} to compile an inventory file"
        )
    host_vars = {"ansible_user": vm.login_user}
    if vm.ip_public:
        host_vars["ansible_host"] = vm.ip_public

    groups["all"]["hosts"][vm.ip_private] = host_vars

    return yaml.dump(groups, Dumper=NoAliasDumper)


def generate_ansible_inventory_file_for_action(
    action: str, m: InstanceManifest, temp_workdir: str
):
    """Places an inventory file into temp_workdir"""
    inventory = get_ansible_inventory_file_str_for_action(action, m.uuid, m.instance_name)  # type: ignore
    if not inventory:
        raise Exception(
            f"Could not compile inventory for action {action} of instance {m.instance_name}"
        )

    with open(os.path.join(temp_workdir, "inventory"), "w") as f:
        f.write(inventory)
    logging.info(
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
    now = datetime.utcnow().replace(microsecond=0)
    now_str = str(now).replace(" ", "_").replace(":", "")
    temp_workdir = os.path.join(
        os.path.expanduser(temp_workdir_root),
        manifest.instance_name,
        action,
        now_str,
    )

    logging.debug("Ensuring temp exec dir %s ...", temp_workdir)
    os.makedirs(temp_workdir, exist_ok=True)

    handler_dir_to_fork = os.path.join(ANSIBLE_ROOT, manifest.api_version)
    if not os.path.exists(handler_dir_to_fork):
        raise Exception(f"Ansible folder at {handler_dir_to_fork} not found")
    # Copy the whole Ansible dir for now into temp dir
    logging.info(
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
        os.path.join(temp_workdir, "vars", "instance_manifest.yml"), "w"
    ) as f:
        f.write(str(manifest.original_manifest))

    if manifest.session_vars:
        with open(
            os.path.join(temp_workdir, "vars", "engine_overrides.yml"), "w"
        ) as f:
            f.write(yaml.dump(manifest.session_vars))

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


def register_results_in_cmdb(
    action: str, output_params_merged: dict, m: InstanceManifest
) -> None:
    if action == constants.ACTION_DESTROY_INSTANCE:
        cmdb.finalize_destroy_instance(m)
        cmdb.mark_manifest_snapshot_as_succeeded(m)
    elif action == constants.ACTION_INSTANCE_SETUP:
        cmdb.finalize_instance_setup(m)
        cmdb.mark_manifest_snapshot_as_succeeded(m)


def run_ansible_handler(
    action: str,
    temp_workdir: str,
    executable_full_path: str,
    m: InstanceManifest,
) -> dict:
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
        return {}

    logging.info(
        "Handler %s finished - retcode: %s", executable_full_path, p.returncode
    )

    output_params = collect_output_params_from_handler_temp_dir(
        temp_workdir, action
    )
    merged_output_params = merge_action_output_params(
        output_params, m.session_vars
    )

    register_results_in_cmdb(action, merged_output_params, m)

    return merged_output_params


def generate_ansible_run_script_for_action(
    action: str, temp_workdir: str, m: InstanceManifest
) -> str:
    """Currently invoking Ansible via Bash but might want to look at ansible-runner later"""
    extra_args = ""
    if not m.vault_password_file and default_vault_password_file:
        m.vault_password_file = os.path.expanduser(default_vault_password_file)
    if m.vault_password_file:
        extra_args = "--vault-password-file " + m.vault_password_file
    run_template = f"""#!/bin/bash

echo "Starting at `date`"

set -e

EXTRA_ARGS="{extra_args}"

ansible-galaxy install -r requirements.yml

echo "ansible-playbook -i inventory $EXTRA_ARGS {action}.yml"
ansible-playbook -i inventory $EXTRA_ARGS {action}.yml

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
    """Executes the tuning profile if exists and returns lines that would be added to pg_config.extra_config_lines"""
    if (
        not mf.pg_config.tuning_profile
        or mf.pg_config.tuning_profile == "none"
    ):
        return []
    profile_path_to_run = os.path.join(
        tuning_profiles_path,
        mf.pg_config.tuning_profile.strip().lower() + ".py",
    )
    if not os.path.exists(profile_path_to_run):
        logger.warning(
            "Tuning profile %s not found from %s, skipping tuning for instance %s",
            mf.pg_config.tuning_profile,
            profile_path_to_run,
            mf.instance_name,
        )
        return []
    tuning_input: dict = mf.vm.model_dump()
    tuning_input["cloud"] = mf.cloud
    tuning_input["postgres_version"] = mf.postgres_version
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
            mf.pg_config.tuning_profile,
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
        and m.pg_config.tuning_profile
        and m.pg_config.tuning_profile.strip().lower() != "none"
    ):
        logger.info(
            "Applying Postgres tuning profile %s to given hardware ...",
            m.pg_config.tuning_profile,
        )
        tuned_config_lines = apply_tuning_profile(m)
        logger.info(
            "%s config lines will be added to postgresql.conf",
            len(tuned_config_lines),
        )
        merged_config_lines = (
            merge_user_and_tuned_non_conflicting_config_params(
                tuned_config_lines,
                m.pg_config.extra_config_lines.copy(),
            )
        )
        if merged_config_lines:
            m.session_vars["pg_config"] = {}
            m.session_vars["pg_config"][
                "extra_config_lines"
            ] = merged_config_lines


def run_action(action: str, m: InstanceManifest) -> tuple[bool, dict]:
    """Returns: (OK, action outputs)
    Steps:
    - Copy handler folder to a temp directory
    - Move manifests to "inputs" folder
    - Start a subprocess and add it to actions_in_progress
    - Collect "output" folder contents on successful exit
    """

    logging.info(
        "Starting action %s for instance %s ...",
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
        "Starting handler for action %s of instance %s, log at %s",
        action,
        m.instance_name,
        os.path.join(temp_workdir, "ansible.log"),
    )

    outputs = run_ansible_handler(
        action, temp_workdir, executable_full_path, m
    )

    return True, outputs


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
    running_operator_vms_in_region = (
        cloud_api.get_all_operator_vms_in_manifest_region(m)
    )
    if m.instance_name in running_operator_vms_in_region:
        vm = cmdb.get_latest_vm_by_uuid(m.uuid)
        if vm:
            return False, vm.provider_id
    if m.instance_name not in running_operator_vms_in_region:
        logger.warning(
            "Detected a missing VM for instance %s (%s) - %s ...",
            m.instance_name,
            m.cloud,
            "NOT creating (--dry-run)" if dry_run else "creating",
        )
        cmdb.mark_any_active_vms_as_deleted(m)

    instance_info = preprocess_ensure_vm_action(m)

    cloud_vm, created = ensure_spot_vm(m, dry_run=dry_run)
    if dry_run:
        return False, "dummy"

    cmdb.finalize_ensure_vm(m, instance_info, cloud_vm)

    return True, cloud_vm.provider_id


def destroy_instance(m: InstanceManifest):
    run_action(constants.ACTION_DESTROY_INSTANCE, m)

    if m.destroy_backups:
        run_action(constants.ACTION_DESTROY_BACKUPS, m)


def do_main_loop(
    cli_dry_run: bool = False,
    cli_env_manifest: InstanceManifest | None = None,
    cli_user_manifest_path: str = "",
    cli_vault_password_file: str = "",
    cli_main_loop_interval_s: int = 60,
):
    global dry_run
    dry_run = cli_dry_run
    global default_vault_password_file
    default_vault_password_file = cli_vault_password_file

    first_loop = True
    loops = 0

    while True:
        loops += 1
        logger.debug("Starting main loop iteration %s ...", loops)

        try:
            # Step 0 - load manifest from CLI args / full adhoc ENV manifest or manifest file
            m: InstanceManifest = None  # type: ignore
            if cli_env_manifest and cli_env_manifest.instance_name:
                (
                    logger.info(
                        "Processing manifest for instance %s set via ENV ...",
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

            # Step 1 - register or update manifest in CMDB

            instance = cmdb.get_instance_by_name_cloud(m)
            m.fill_in_defaults()
            if not instance:
                m.uuid = cmdb.register_instance_or_get_uuid(m)
            else:
                m.uuid = instance.uuid  # type: ignore

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

            # Set AWS creds for non-manifest related API calls
            m.decrypt_secrets_if_any()
            if m.aws.access_key_id and m.aws.secret_access_key:
                aws_client.AWS_ACCESS_KEY_ID = m.aws.access_key_id
                aws_client.AWS_SECRET_ACCESS_KEY = m.aws.secret_access_key
            if m.aws.profile_name:
                aws_client.AWS_PROFILE = m.aws.profile_name

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

            if not instance and m.is_expired():
                if first_loop and not current_manifest_applied_successfully:
                    destroy_instance(m)
                else:
                    logger.debug(
                        "Instance '%s' expired, NoOp",
                        m.instance_name,
                    )
                raise NoOp()

            if m.is_expired() and not prev_success_manifest.is_expired():  # type: ignore
                destroy_instance(m)
                raise NoOp()

            vm_created_recreated, vm_provider_id = ensure_vm(m)
            if vm_created_recreated:
                logger.info(
                    "Sleeping 30s as VM %s created, give time to boot",
                    vm_provider_id,
                )
                time.sleep(30)

            if dry_run:  # Bail as next actions depend on output of ensure_vm
                raise NoOp()

            diff = m.diff_manifests(
                prev_success_manifest, original_manifests_only=True
            )

            if (
                vm_created_recreated
                or diff
                or not current_manifest_applied_successfully
            ):
                # Just reconfigure the VM if any changes discovered, relying on Ansible idempotence
                logging.info(
                    "Re-configuring Postgres for instance %s ...",
                    m.instance_name,
                )
                if diff:
                    logging.info("Detected manifest changes: %s", diff)

                run_action(constants.ACTION_INSTANCE_SETUP, m)

            else:
                logger.info(
                    "No state changes detected for instance %s (%s), VM %s",
                    m.instance_name,
                    m.cloud,
                    vm_provider_id,
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

        first_loop = False
        logger.info(
            "Main loop finished. Sleeping for %s s ...",
            cli_main_loop_interval_s,
        )
        time.sleep(cli_main_loop_interval_s)
