import datetime
import fcntl
import logging
import os.path
import shutil

from dateutil.parser import isoparse
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
    vm_only: bool = to_bool(
        os.getenv("PGSO_VM_ONLY", "false")
    )  # No Ansible / Postgres setup
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
    postgres_version: str = os.getenv("PGSO_PG_MAJOR_VERSION", "16")
    instance_types: str = os.getenv(
        "PGSO_INSTANCE_TYPES", ""
    )  # i3.xlarge,i3.2xlarge
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
    user_tags: str = os.getenv("PGSO_USER_TAGS", "")  # key=val,key2=val2
    admin_user: str = os.getenv("PGSO_ADMIN_USER", "")
    admin_user_password: str = os.getenv("PGSO_ADMIN_USER_PASSWORD", "")
    aws_access_key_id: str = os.getenv("PGSO_AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("PGSO_AWS_SECRET_ACCESS_KEY", "")
    vm_host: str = os.getenv(
        "PGSO_VM_HOST", ""
    )  # Skip creation and use the provided IP
    vm_login_user: str = os.getenv(
        "PGSO_LOGIN_USER", ""
    )  # Default SSH key will be used
    destroy_file_base_path: str = os.getenv(
        "PGSO_DESTROY_FILE_BASE_PATH", "/tmp/destroy-"
    )  # If a file named base+instance detected, the instance is expired and the program exits
    setup_finished_callback: str = os.getenv(
        "PGSO_SETUP_FINISHED_CALLBACK", ""
    )  # An optional executable to propagate the connect string somewhere
    backup_s3_bucket: str = os.getenv(
        "PGSO_BACKUP_S3_BUCKET", ""
    )  # If set, pgbackrest will be configured
    backup_cipher: str = os.getenv(
        "PGSO_BACKUP_CIPHER", ""
    )  # pgbackrest cipher password
    backup_retention_days: str = os.getenv("PGSO_BACKUP_RETENTION_DAYS", "1")
    backup_s3_key: str = os.getenv("PGSO_BACKUP_S3_KEY", "")
    backup_s3_key_secret: str = os.getenv("PGSO_BACKUP_S3_KEY_SECRET", "")


args: ArgumentParser | None = None


def validate_and_parse_args() -> ArgumentParser:
    args = ArgumentParser(
        prog="pg-spot-operator",
        description="Maintains Postgres on Spot VMs",
        underscores_to_dashes=True,
    ).parse_args()

    return args


def compile_manifest_from_cmdline_params(args: ArgumentParser) -> str:
    if not args.instance_name:
        raise Exception("Can't compile a manifest --instance-name not set")
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
        if args.expiration_date[0] in ('"', "'"):
            mfs += f"expiration_date: {args.expiration_date}\n"
        else:
            mfs += f'expiration_date: "{args.expiration_date}"\n'
    if args.public_ip:
        mfs += f"assign_public_ip: {str(args.public_ip).lower()}\n"
    if args.postgres_version:
        mfs += f"postgres_version: {args.postgres_version}\n"
    if args.setup_finished_callback:
        mfs += f"setup_finished_callback: {args.setup_finished_callback}\n"
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
    if args.instance_types:
        mfs += "  instance_types:\n"
        for ins_type in args.instance_types.split(","):
            mfs += f"    - {ins_type}\n"
    if args.vm_host:
        mfs += f"  host: {args.vm_host}\n"
    if args.vm_login_user:
        mfs += f"  login_user: {args.vm_login_user}\n"
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
    if args.user_tags:
        mfs += "user_tags:\n"
        for tag_set in args.user_tags.split(","):
            key_val = tag_set.split("=")
            mfs += f"  {key_val[0]}: {key_val[1]}\n"
    if args.admin_user and args.admin_user_password:
        mfs += "pg:\n"
        mfs += f"  admin_user: {args.admin_user}\n"
        mfs += f"  admin_user_password: {args.admin_user_password}\n"
    if args.backup_s3_bucket:
        mfs += "backup:\n"
        mfs += "  type: pgbackrest\n"
        mfs += f"  s3_bucket: {args.backup_s3_bucket}\n"
        mfs += f"  retention_days: {args.backup_retention_days}\n"
        mfs += f"  s3_key: {args.backup_s3_key}\n"
        mfs += f"  s3_key_secret: {args.backup_s3_key_secret}\n"
        if args.backup_cipher:
            mfs += "  encryption: true\n"
            mfs += f"  cipher_password: {args.backup_cipher}\n"
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
        logger.debug("Compiling a manifest from CLI args ...")
        return compile_manifest_from_cmdline_params(args)
    raise Exception("Could not find / compile a manifest string")


def check_cli_args_valid(args: ArgumentParser):
    fixed_vm = bool(args.vm_login_user and args.vm_host)
    if args.instance_name and not fixed_vm:
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
    if args.vm_host or args.vm_login_user:
        if not (args.vm_host and args.vm_login_user):
            logger.error(
                "Both --vm-host / --vm-login-user need to be provided",
            )
            exit(1)
    if args.user_tags:
        for tag_set in args.user_tags.split(","):
            key_val = tag_set.split("=")
            if len(key_val) != 2:
                logger.error(
                    "Invalid tag item, expecting 'key=val,key2=val2', got %s",
                    args.user_tags,
                )
                exit(1)
    if args.admin_user or args.admin_user_password:
        if not (args.admin_user and args.admin_user_password):
            logger.error(
                "Both --admin-user / --admin-user-password need to be provided",
            )
            exit(1)
    if args.instance_types and "." not in args.instance_types:
        for ins in args.instance_types.split(","):
            if "." not in ins:
                logger.error(
                    "--instance-types expected input format: iX.large,iX.xlarge"
                )
                exit(1)
    if args.backup_s3_bucket and not (
        args.backup_s3_key and args.backup_s3_key
    ):
        logger.error(
            "Enabling backups (--backup-s3-bucket) requires --backup-s3-key / --backup-s3-key-secret",
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


def ensure_single_instance_running(instance_name: str):
    """https://stackoverflow.com/questions/380870/make-sure-only-a-single-instance-of-a-program-is-running"""

    lockfile = f"/tmp/pg_spot_operator_instance-{instance_name}.lock"
    lock_file_pointer = os.open(lockfile, os.O_WRONLY | os.O_CREAT)

    try:
        fcntl.lockf(lock_file_pointer, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        logger.error(
            f"Another instance already running? Delete lockfile at {lockfile} if not"
        )
        exit(1)


def clean_up_old_logs_if_any(config_dir: str, old_threshold_days: int = 7):
    """Leaves empty instance_name/action folders in place though to indicate what operations have happened
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
        ):  # /home/krl/.pg-spot-operator/tmp/pg1/single_instance_setup/2024-10-02_093928/ansible.log
            if not (d.startswith("20") and "-" in d):  # 2024-10-02_113800
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

    check_cli_args_valid(args)

    if args.check_manifest:
        check_manifest_and_exit(args)

    logger.debug("Args: %s", args.as_dict()) if args.verbose else None

    if not args.dry_run:
        ensure_single_instance_running(args.instance_name)

    if args.teardown_region:
        operator.teardown_region(
            args.region,
            args.aws_access_key_id,
            args.aws_secret_access_key,
            args.dry_run,
        )
        logger.info("Teardown complete")
        exit(0)

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
    logger.debug("%s schema migration applied", applied_count)

    if not args.dry_run:
        clean_up_old_logs_if_any(args.config_dir)

    logger.info("Entering main loop")

    operator.do_main_loop(
        cli_env_manifest=env_manifest,
        cli_dry_run=args.dry_run,
        cli_vault_password_file=args.vault_password_file,
        cli_user_manifest_path=args.manifest_path,
        cli_main_loop_interval_s=args.main_loop_interval_s,
        cli_vm_host=args.vm_host,
        cli_vm_login_user=args.vm_login_user,
        cli_vm_only=args.vm_only,
        cli_destroy_file_base_path=args.destroy_file_base_path,
    )
