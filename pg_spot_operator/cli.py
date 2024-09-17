import logging
import os.path

from tap import Tap

from pg_spot_operator import cmdb, manifests, operator
from pg_spot_operator.cmdb_impl import schema_manager
from pg_spot_operator.manifests import InstanceManifest

logger = logging.getLogger(__name__)


def to_bool(param: str) -> bool:
    if not param:
        return False
    if param.strip().lower() == "on":
        return True
    if param.strip().lower()[0] == "t":
        return True
    if param.strip().lower()[0] == "y":
        return True
    return False


class ArgumentParser(Tap):
    show_help: bool = to_bool(
        os.getenv("PGSO_SHOW_HELP", "False")
    )  # Don't actually execute actions
    manifest_path: str = os.getenv(
        "PGSO_MANIFEST_PATH", ""
    )  # User manifest path
    ansible_path: str = os.getenv("PGSO_ANSIBLE_PATH", "./ansible")
    main_loop_interval_s: int = int(
        os.getenv("PGSO_MAIN_LOOP_INTERVAL_S")
        or 60  # Increase if causing too many calls to the cloud API
    )
    config_dir: str = os.getenv(
        "PGSO_CONFIG_DIR", "~/.pg-spot-operator"
    )  # For internal state keeping
    sqlite_path: str = os.getenv(
        "PGSO_SQLITE_PATH", "~/.pg-spot-operator/pgso.db"
    )
    default_vault_password_file: str = os.getenv(
        "PGSO_DEFAULT_VAULT_PASSWORD_FILE", ""
    )  # Can also be set on instance level
    verbose: bool = to_bool(os.getenv("PGSO_VERBOSE", "false"))  # More chat
    check_manifest: bool = to_bool(
        os.getenv("PGSO_CHECK_MANIFEST", "false")
    )  # Validate instance manifests and exit
    dry_run: bool = to_bool(
        os.getenv("PGSO_DRY_RUN", "false")
    )  # Just resolve the VM instance type
    no_recreate: bool = to_bool(
        os.getenv("PGSO_NO_RECREATE", "false")
    )  # Don't replace interrupted VMs
    manifest: str = os.getenv("PGSO_MANIFEST", "")  # Manifest to process
    teardown: bool = to_bool(
        os.getenv("PGSO_TEARDOWN", "false")
    )  # Delete VM and other created resources
    instance_name: str = os.getenv(
        "PGSO_INSTANCE_NAME", ""
    )  # If set other below params become relevant
    pg_major_version: str = os.getenv("PGSO_PG_MAJOR_VERSION", "16")
    instance_type: str = os.getenv("PGSO_INSTANCE_TYPE", "")
    cloud: str = os.getenv("PGSO_CLOUD", "aws")
    region: str = os.getenv("PGSO_REGION", "")
    zone: str = os.getenv("PGSO_ZONE", "")
    cpu_min: int = int(os.getenv("PGSO_CPU_MIN", "0"))
    ram_min: int = int(os.getenv("PGSO_RAM_MIN", "0"))
    storage_min: int = int(os.getenv("PGSO_STORAGE_MIN", "0"))
    storage_type: str = os.getenv("PGSO_STORAGE_TYPE", "network")
    expires_on: str = os.getenv(
        "PGSO_EXPIRES_ON", ""
    )  # Instance expiry / teardwon timestamp
    public_ip: bool = to_bool(os.getenv("PGSO_PUBLIC_IP", "true"))
    cpu_architecture: str = os.getenv("PGSO_CPU_ARCHITECTURE", "")


args: ArgumentParser | None = None


def validate_and_parse_args() -> ArgumentParser:
    args = ArgumentParser(
        prog="pg-spot-operator",
        description="Maintains Postgres on Spot VMs",
        underscores_to_dashes=True,
    ).parse_args()

    return args


def compile_manifest_from_cmdline_params(args: ArgumentParser) -> str:
    if not (args.instance_name and args.region):
        raise Exception(
            "Can't compile a manifest - required params not set: --instance-name, --region"
        )
    mfs = f"""
---
api_version: v1
kind: pg_spot_operator_instance
cloud: {args.cloud}
region: {args.region}
instance_name: {args.instance_name}
"""
    if args.zone:
        mfs += f"availability_zone: {args.zone}\n"
    if args.expires_on:
        mfs += f"expires_on: {args.expires_on}\n"
    if args.public_ip:
        mfs += f"assign_public_ip: {str(args.public_ip).lower()}\n"
    if args.pg_major_version:
        mfs += f"pg:\n  major_version: {args.pg_major_version}\n"
    mfs += "vm:\n"
    if args.cpu_architecture:
        mfs += f"  cpu_architecture: {args.cpu_architecture}\n"
    if args.cpu_min:
        mfs += f"  cpu_min: {args.cpu_min}\n"
    if args.ram_min:
        mfs += f"  ram_min: {args.ram_min}\n"
    if args.storage_min:
        mfs += f"  storage_min: {args.storage_min}\n"
    if args.storage_type:
        mfs += f"  storage_type: {args.storage_type}\n"
    if args.instance_type:
        mfs += f"  instance_type: {args.instance_type}\n"
    # logger.debug("Compiled manifest: %s", mfs)
    return mfs


def get_manifest_from_args_as_string(args: ArgumentParser) -> str:
    if args.manifest:
        logger.info("Using the provided --manifest arg ...")
        return args.manifest
    elif args.manifest_path:
        logger.info("Using the provided --manifest-file arg ...")
        with open(args.manifest_path) as f:
            return f.read()
    elif args.instance_name:
        logger.info("Compiling a manifest from CLI args ...")
        return compile_manifest_from_cmdline_params(args)
    raise Exception("Could not find / compile a manifest string")


def try_load_manifest(manifest_str: str) -> InstanceManifest | None:
    try:
        mf = manifests.load_manifest_from_string(manifest_str)
        mf.original_manifest = manifest_str
        return mf
    except Exception as e:
        logger.error(
            "Failed to load manifest: %s",
            e,
        )
        return None


def check_manifest_and_exit(args: ArgumentParser):
    manifest_str = get_manifest_from_args_as_string(args)
    m = try_load_manifest(manifest_str)
    if not m:
        logger.error("Failed manifest: %s", manifest_str)
        exit(1)

    logger.info(
        "Valid manifest provided for instance %s (%s)",
        m.instance_name,
        m.cloud,
    )
    logger.debug(manifest_str)
    logger.info("Exiting due to --check-manifests")
    exit(0)


def main():  # pragma: no cover
    global args
    args = validate_and_parse_args()

    logging.basicConfig(
        format=(
            "%(asctime)s %(levelname)s %(threadName)s %(filename)s:%(lineno)d %(message)s"
            if args.verbose
            else "%(asctime)s %(levelname)s %(message)s"
        ),
        level=(logging.DEBUG if args.verbose else logging.INFO),
    )

    if args.show_help:
        args.print_help()
        exit(0)

    if args.check_manifest:
        check_manifest_and_exit(args)

    logger.debug("Args: %s", args.as_dict()) if args.verbose else None

    cmdb.init_engine_and_check_connection(args.sqlite_path)

    applied_count = schema_manager.do_ddl_rollout_if_needed(
        (os.path.expanduser(args.sqlite_path))
    )
    logger.info("%s schema migration applied", applied_count)

    env_manifest: InstanceManifest | None = None
    if args.manifest or args.instance_name:
        manifest_str = get_manifest_from_args_as_string(args)
        env_manifest = try_load_manifest(manifest_str)
        if not env_manifest:
            logger.exception("Failed to parse manifest from CLI args")
            logger.error("Manifest: %s", manifest_str)
            exit(1)
        if args.teardown:  # Delete instance and any attached resources
            env_manifest.expires_on = "now"

    logger.info("Entering main loop")

    operator.cli_args = args

    operator.do_main_loop(
        cli_env_manifest=env_manifest,
        cli_dry_run=args.dry_run,
        cli_default_vault_password_file=args.default_vault_password_file,
        cli_user_manifest_path=args.manifest_path,
        cli_main_loop_interval_s=args.main_loop_interval_s,
    )
