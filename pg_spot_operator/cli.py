import fcntl
import logging
import os.path

from tap import Tap

from pg_spot_operator import cmdb, manifests, operator
from pg_spot_operator.cmdb_impl import schema_manager
from pg_spot_operator.manifests import InstanceManifest

SQLITE_DBNAME = "pgso.db"

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
    vault_password_file: str = os.getenv(
        "PGSO_VAULT_PASSWORD_FILE", ""
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
    teardown_region: bool = to_bool(
        os.getenv("PGSO_TEARDOWN_REGION", "false")
    )  # Delete all operator tagged resources in region
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
    expiration_date: str = os.getenv(
        "PGSO_EXPIRATION_DATE", ""
    )  # ISO 8601 datetime
    public_ip: bool = to_bool(os.getenv("PGSO_PUBLIC_IP", "true"))
    cpu_architecture: str = os.getenv("PGSO_CPU_ARCHITECTURE", "")
    ssh_keys: str = os.getenv("PGSO_SSH_KEYS", "")  # Comma separated
    tuning_profile: str = os.getenv("PGSO_TUNING_PROFILE", "default")
    aws_access_key_id: str = os.getenv("PGSO_AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("PGSO_AWS_SECRET_ACCESS_KEY", "")


args: ArgumentParser | None = None


def validate_and_parse_args() -> ArgumentParser:
    args = ArgumentParser(
        prog="pg-spot-operator",
        description="Maintains Postgres on Spot VMs",
        underscores_to_dashes=True,
    ).parse_args()

    return args


def compile_manifest_from_cmdline_params(args: ArgumentParser) -> str:
    if not args.instance_name or not (args.region or args.zone):
        raise Exception(
            "Can't compile a manifest - required params not set: --instance-name, --region"
        )
    mfs = f"""
---
api_version: v1
kind: pg_spot_operator_instance
cloud: {args.cloud}
instance_name: {args.instance_name}
"""
    if args.region:
        mfs += f"region: {args.region}\n"
    if args.zone:
        mfs += f"availability_zone: {args.zone}\n"
    if args.expiration_date:
        mfs += f"expiration_date: {args.expiration_date}\n"
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
    if args.ssh_keys:
        mfs += "access:\n  extra_ssh_pub_keys:\n"
        for key in args.ssh_keys.split(","):
            mfs += "    - " + key.strip() + "\n"
    if args.tuning_profile:
        mfs += f"pg_config:\n  tuning_profile: {args.tuning_profile}\n"
    if args.aws_access_key_id and args.aws_secret_access_key:
        mfs += "aws:\n"
        mfs += f"  access_key_id: {args.aws_access_key_id}\n"
        mfs += f"  secret_access_key: {args.aws_secret_access_key}\n"
    return mfs


def get_manifest_from_args_as_string(args: ArgumentParser) -> str:
    if args.manifest:
        logger.info("Using the provided --manifest arg ...")
        return args.manifest
    elif args.manifest_path:
        logger.info(
            "Using the provided --manifest-path at %s ...", args.manifest_path
        )
        with open(args.manifest_path) as f:
            return f.read()
    elif args.instance_name:
        logger.info("Compiling a manifest from CLI args ...")
        return compile_manifest_from_cmdline_params(args)
    raise Exception("Could not find / compile a manifest string")


def check_cli_args_valid(args: ArgumentParser):
    if args.instance_name:
        if not args.region and not args.zone:
            logger.error("--region input expected for single args")
            exit(1)
        if not args.instance_name:
            logger.error("--instance-name input expected for single args")
            exit(1)
        if not args.storage_min:
            logger.error("--storage-min input expected for single args")
            exit(1)
        if args.region and len(args.region.split("-")) != 3:
            logger.error(
                """Unexpected --region format, run "PAGER= aws account list-regions --query 'Regions[*].[RegionName]' --output text" for a complete listing""",
            )
            exit(1)
        if args.zone and len(args.zone.split("-")) not in (3, 5):
            logger.error(
                """Unexpected --zone format, expecting smth like: eu-west-1b or us-west-2-lax-1a""",
            )
            exit(1)
    if args.teardown_region and not args.region:
        logger.error(
            """Unexpected --teardown-region requires --region set""",
        )
        exit(1)

    if args.vault_password_file:
        if not os.path.exists(os.path.expanduser(args.vault_password_file)):
            logger.error(
                "--vault-password-file not found at %s",
                args.vault_password_file,
            )
            exit(1)


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

    if "$ANSIBLE_VAULT" in m.original_manifest:
        if not m.vault_password_file and args.vault_password_file:
            m.vault_password_file = args.vault_password_file
        secrets_found, decrypted = m.decrypt_secrets_if_any()
        if secrets_found != decrypted:
            logger.error(
                "Failed to decrypt secrets, is --vault-password-file %s correct?",
                m.vault_password_file or args.vault_password_file,
            )
            exit(1)

    logger.info(
        "Valid manifest provided for instance %s (%s)",
        m.instance_name,
        m.cloud,
    )
    logger.debug("Manifest: %s", manifest_str)
    logger.info("Exiting due to --check-manifests")
    exit(0)


def ensure_single_instance_running():
    """https://stackoverflow.com/questions/380870/make-sure-only-a-single-instance-of-a-program-is-running"""

    lock_file_pointer = os.open(
        "/tmp/pg_spot_operator_instance.lock", os.O_WRONLY | os.O_CREAT
    )

    try:
        fcntl.lockf(lock_file_pointer, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        logger.error(
            "Another instance already running? Delete /tmp/pg_spot_operator_instance.lock if not"
        )
        exit(1)


def main():  # pragma: no cover

    ensure_single_instance_running()

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

    check_cli_args_valid(args)

    if args.check_manifest:
        check_manifest_and_exit(args)

    logger.debug("Args: %s", args.as_dict()) if args.verbose else None

    env_manifest: InstanceManifest | None = None
    if args.manifest or args.instance_name:
        manifest_str = get_manifest_from_args_as_string(args)
        env_manifest = try_load_manifest(manifest_str)
        if not env_manifest:
            logger.exception("Failed to parse manifest from CLI args")
            logger.error("Manifest: %s", manifest_str)
            exit(1)
        if args.teardown:  # Delete instance and any attached resources
            env_manifest.expiration_date = "now"

    cmdb.init_engine_and_check_connection(
        os.path.join(args.config_dir, SQLITE_DBNAME)
    )

    applied_count = schema_manager.do_ddl_rollout_if_needed(
        os.path.join(args.config_dir, SQLITE_DBNAME)
    )
    logger.info("%s schema migration applied", applied_count)

    if args.teardown_region:
        operator.teardown_region(
            args.region,
            args.aws_access_key_id,
            args.aws_secret_access_key,
            args.dry_run,
        )
        logger.info("Teardown complete")
        exit(0)

    logger.info("Entering main loop")

    operator.do_main_loop(
        cli_env_manifest=env_manifest,
        cli_dry_run=args.dry_run,
        cli_vault_password_file=args.vault_password_file,
        cli_user_manifest_path=args.manifest_path,
        cli_main_loop_interval_s=args.main_loop_interval_s,
    )
