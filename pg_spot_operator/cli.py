import fcntl
import logging
import os.path

import yaml
from tap import Tap

from pg_spot_operator import cloud_api, cmdb, manifests, operator
from pg_spot_operator.cloud_impl.aws_client import set_access_keys
from pg_spot_operator.cmdb_impl import schema_manager
from pg_spot_operator.manifests import InstanceManifest
from pg_spot_operator.operator import clean_up_old_logs_if_any

SQLITE_DBNAME = "pgso.db"

logger = logging.getLogger(__name__)


def str_to_bool(param: str) -> bool:
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
    show_help: bool = str_to_bool(
        os.getenv("PGSO_SHOW_HELP", "False")
    )  # Don't actually execute actions
    manifest_path: str = os.getenv(
        "PGSO_MANIFEST_PATH", ""
    )  # User manifest path
    ansible_path: str = os.getenv(
        "PGSO_ANSIBLE_PATH", ""
    )  # Use a non-default Ansible path
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
    verbose: bool = str_to_bool(
        os.getenv("PGSO_VERBOSE", "false")
    )  # More chat
    check_price: bool = str_to_bool(
        os.getenv("PGSO_CHECK_PRICE", "false")
    )  # Resolve HW reqs, show Spot price and exit
    check_manifest: bool = str_to_bool(
        os.getenv("PGSO_CHECK_MANIFEST", "false")
    )  # Validate instance manifests and exit
    dry_run: bool = str_to_bool(
        os.getenv("PGSO_DRY_RUN", "false")
    )  # Just resolve the VM instance type
    vm_only: bool = str_to_bool(
        os.getenv("PGSO_VM_ONLY", "false")
    )  # No Ansible / Postgres setup
    connstr_output_only: bool = str_to_bool(
        os.getenv("PGSO_CONNSTR_OUTPUT_ONLY", "false")
    )  # Set up Postgres, print connstr and exit
    manifest: str = os.getenv("PGSO_MANIFEST", "")  # Manifest to process
    teardown: bool = str_to_bool(
        os.getenv("PGSO_TEARDOWN", "false")
    )  # Delete VM and other created resources
    teardown_region: bool = str_to_bool(
        os.getenv("PGSO_TEARDOWN_REGION", "false")
    )  # Delete all operator tagged resources in region
    instance_name: str = os.getenv(
        "PGSO_INSTANCE_NAME", ""
    )  # If set other below params become relevant
    postgresql_version: int = int(os.getenv("PGSO_POSTGRESQL_VERSION", "16"))
    instance_types: str = os.getenv(
        "PGSO_INSTANCE_TYPES", ""
    )  # i3.xlarge,i3.2xlarge
    cloud: str = os.getenv("PGSO_CLOUD", "aws")
    region: str = os.getenv("PGSO_REGION", "")
    zone: str = os.getenv("PGSO_ZONE", "")
    cpu_min: int = int(os.getenv("PGSO_CPU_MIN", "0"))
    cpu_max: int = int(os.getenv("PGSO_CPU_MAX", "0"))
    selection_strategy: str = os.getenv("PGSO_SELECTION_STRATEGY", "cheapest")
    ram_min: int = int(os.getenv("PGSO_RAM_MIN", "0"))
    storage_min: int = int(os.getenv("PGSO_STORAGE_MIN", "0"))
    storage_type: str = os.getenv("PGSO_STORAGE_TYPE", "network")
    expiration_date: str = os.getenv(
        "PGSO_EXPIRATION_DATE", ""
    )  # ISO 8601 datetime
    self_terminate: bool = str_to_bool(
        os.getenv("PGSO_SELF_TERMINATE", "false")
    )
    assign_public_ip: bool = str_to_bool(
        os.getenv("PGSO_ASSIGN_PUBLIC_IP", "true")
    )
    cpu_architecture: str = os.getenv("PGSO_CPU_ARCHITECTURE", "")
    ssh_keys: str = os.getenv("PGSO_SSH_KEYS", "")  # Comma separated
    tuning_profile: str = os.getenv("PGSO_TUNING_PROFILE", "default")
    user_tags: str = os.getenv("PGSO_USER_TAGS", "")  # key=val,key2=val2
    app_db_name: str = os.getenv("PGSO_APP_DB_NAME", "")
    admin_user: str = os.getenv("PGSO_ADMIN_USER", "")
    admin_user_password: str = os.getenv("PGSO_ADMIN_USER_PASSWORD", "")
    admin_is_superuser: str = os.getenv("PGSO_ADMIN_IS_SUPERUSER", "false")
    os_extra_packages: str = os.getenv(
        "PGSO_OS_EXTRA_PACKAGES", ""
    )  # Comma separated, e.g. postgresql-16-postgis-3,postgresql-16-pgrouting
    shared_preload_libraries: str = os.getenv(
        "PGSO_SHARED_PRELOAD_LIBRARIES", "pg_stat_statements"
    )  # Comma separated
    extensions: str = os.getenv("PGSO_EXTENSIONS", "pg_stat_statements")
    aws_access_key_id: str = os.getenv("PGSO_AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("PGSO_AWS_SECRET_ACCESS_KEY", "")
    aws_security_group_ids: str = os.getenv(
        "PGSO_AWS_SECURITY_GROUP_IDS", ""
    )  # SG rules are "merged" if multiple provided
    aws_vpc_id: str = os.getenv(
        "PGSO_AWS_VPC_ID", ""
    )  # If not set default VPC in region used
    aws_subnet_id: str = os.getenv("PGSO_AWS_SUBNET_ID", "")
    self_terminate_access_key_id: str = os.getenv(
        "PGSO_SELF_TERMINATE_ACCESS_KEY_ID", ""
    )
    self_terminate_secret_access_key: str = os.getenv(
        "PGSO_SELF_TERMINATE_SECRET_ACCESS_KEY", ""
    )
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
    backup_retention_days: int = int(
        os.getenv("PGSO_BACKUP_RETENTION_DAYS", "1")
    )
    backup_s3_key: str = os.getenv("PGSO_BACKUP_S3_KEY", "")
    backup_s3_key_secret: str = os.getenv("PGSO_BACKUP_S3_KEY_SECRET", "")
    monitoring: bool = str_to_bool(os.getenv("PGSO_MONITORING", "false"))
    grafana_externally_accessible: bool = str_to_bool(
        os.getenv("PGSO_GRAFANA_EXTERNALLY_ACCESSIBLE", "true")
    )
    grafana_anonymous: bool = str_to_bool(
        os.getenv("PGSO_GRAFANA_ANONYMOUS", "true")
    )
    ssh_private_key: str = os.getenv(
        "PGSO_SSH_PRIVATE_KEY", ""
    )  # To use a non-default (~/.ssh/id_rsa) SSH key


args: ArgumentParser | None = None


def validate_and_parse_args() -> ArgumentParser:
    args = ArgumentParser(
        prog="pg-spot-operator",
        description="Maintains Postgres on Spot VMs",
        underscores_to_dashes=True,
    ).parse_args()

    return args


def compile_manifest_from_cmdline_params(
    args: ArgumentParser,
) -> InstanceManifest:
    if not args.instance_name:
        raise Exception("Can't compile a manifest --instance-name not set")

    m = InstanceManifest(
        api_version="v1",
        cloud="aws",
        kind="pg_spot_operator_instance",
        instance_name=args.instance_name,
    )

    m.instance_name = args.instance_name
    m.region = args.region
    m.availability_zone = args.zone
    m.expiration_date = args.expiration_date
    m.assign_public_ip = args.assign_public_ip
    m.setup_finished_callback = args.setup_finished_callback
    m.vm.cpu_architecture = args.cpu_architecture
    m.vm.cpu_min = args.cpu_min
    m.vm.cpu_max = args.cpu_max
    m.vm.ram_min = args.ram_min
    m.vm.storage_min = args.storage_min
    m.vm.storage_type = args.storage_type
    if args.instance_types:
        for ins_type in args.instance_types.split(","):
            m.vm.instance_types.append(ins_type)
    m.vm.host = args.vm_host
    m.vm.login_user = args.vm_login_user
    m.vm.instance_selection_strategy = args.selection_strategy
    if args.ssh_keys:
        for key in args.ssh_keys.split(","):
            m.os.ssh_pub_keys.append(key.strip())
    m.aws.security_group_ids = (
        args.aws_security_group_ids.split(",")
        if args.aws_security_group_ids
        else []
    )
    m.aws.vpc_id = args.aws_vpc_id
    m.aws.subnet_id = args.aws_subnet_id
    m.aws.access_key_id = args.aws_access_key_id
    m.aws.secret_access_key = args.aws_secret_access_key
    m.self_terminate = args.self_terminate
    if args.self_terminate:
        m.aws.self_terminate_access_key_id = args.self_terminate_access_key_id
        m.aws.self_terminate_secret_access_key = (
            args.self_terminate_secret_access_key
        )
    if args.user_tags:
        for tag_set in args.user_tags.split(","):
            key_val = tag_set.split("=")
            m.user_tags[key_val[0]] = key_val[1]
    m.postgresql.version = args.postgresql_version
    m.postgresql.admin_user = args.admin_user
    m.postgresql.admin_user_password = args.admin_user_password
    m.postgresql.admin_is_superuser = str_to_bool(args.admin_is_superuser)
    m.postgresql.app_db_name = args.app_db_name
    m.postgresql.tuning_profile = args.tuning_profile
    if args.shared_preload_libraries:
        m.postgresql.config_lines.append(
            "shared_preload_libraries = '"
            + args.shared_preload_libraries.rstrip("'").lstrip("'")
            + "'"
        )
    if args.extensions:
        m.postgresql.extensions = args.extensions.strip().split(",")
    if args.os_extra_packages:
        m.os.extra_packages = args.os_extra_packages.strip().split(",")

    if args.backup_s3_bucket:
        m.backup.type = "pgbackrest"
        m.backup.retention_days = args.backup_retention_days
        m.backup.s3_bucket = args.backup_s3_bucket
        m.backup.s3_key = args.backup_s3_key
        m.backup.s3_key_secret = args.backup_s3_key_secret
        if args.backup_cipher:
            m.backup.encryption = True
            m.backup.cipher_password = args.backup_cipher

    if args.monitoring:
        m.monitoring.prometheus_node_exporter.enabled = True
        m.monitoring.grafana.enabled = True
        m.monitoring.grafana.anonymous_access = args.grafana_anonymous
        m.monitoring.grafana.externally_accessible = (
            args.grafana_externally_accessible
        )

    m.ansible.private_key = args.ssh_private_key

    m.original_manifest = yaml.dump(m.model_dump(exclude_none=True))

    return m


def get_manifest_from_args(args: ArgumentParser) -> InstanceManifest | None:
    if args.manifest:
        logger.info("Using the provided --manifest arg ...")
        return try_load_manifest(args.manifest)
    elif args.manifest_path:
        logger.info(
            "Using the provided --manifest-path at %s ...", args.manifest_path
        )
        with open(args.manifest_path) as f:
            return try_load_manifest(f.read())
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
        if not args.storage_min and not (
            args.teardown or args.teardown_region
        ):
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
    if args.self_terminate and not args.expiration_date:
        logger.error(
            "--self-terminate assumes also --expiration-date set",
        )
        exit(1)
    if args.self_terminate and not (
        args.self_terminate_access_key_id
        and args.self_terminate_secret_access_key
    ):
        logger.error(
            "Self-termination on expiration date requires --self-terminate-access-key-id and --self-terminate-secret-access-key",
        )
        exit(1)
    if args.ssh_private_key and not (
        args.teardown
        or args.teardown_region
        or args.dry_run
        or args.check_price
        or args.check_manifest
    ):
        if not os.path.exists(os.path.expanduser(args.ssh_private_key)):
            logger.error("--ssh-private-key file not found")
            exit(1)
        if not os.path.exists(
            os.path.expanduser(args.ssh_private_key + ".pub")
        ):
            logger.error("--ssh-private-key .pub file not found")
            exit(1)
    if (
        args.ansible_path
        and not (
            args.check_price
            or args.check_manifest
            or args.teardown
            or args.teardown_region
        )
        and not os.path.exists(os.path.expanduser(args.ansible_path))
    ):
        logger.error("--ansible-path %s not found", args.ansible_path)
        exit(1)
    if args.aws_vpc_id and not args.aws_vpc_id.startswith("vpc-"):
        logger.error(
            "Invalid --aws-vpc-id, expecting to start with 'vpc-'",
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
    m = get_manifest_from_args(args)
    if not m:
        logger.error("Failed to manifest")
        exit(1)

    m.model_validate(m)
    logger.debug("model_validate() OK")
    if not args.manifest and not args.manifest_path:
        logger.debug("Compiled manifest: %s", m.original_manifest)

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


def resolve_manifest_and_display_price(
    m: InstanceManifest | None, user_manifest_path: str
) -> None:
    if not m and user_manifest_path:
        with open(
            os.path.expanduser(os.path.expanduser(user_manifest_path))
        ) as f:
            m = manifests.try_load_manifest_from_string(f.read())  # type: ignore
    if not m:
        raise Exception("Valid InstanceManifest expected")

    logger.info(
        "Resolving HW requirements to actual instance types / prices using instance selection strategy: %s ...",
        m.vm.instance_selection_strategy,
    )

    # Set AWS creds
    m.decrypt_secrets_if_any()
    set_access_keys(
        m.aws.access_key_id, m.aws.secret_access_key, m.aws.profile_name
    )

    cheapest_skus = cloud_api.get_cheapest_skus_for_hardware_requirements(m)
    if not cheapest_skus:
        logger.error(
            f"No SKUs matching HW requirements found for instance {m.instance_name} in region / zone {m.region or m.availability_zone}"
        )
        exit(1)
    sku = cheapest_skus[0]
    logger.info("Instance type selected: %s (%s)", sku.instance_type, sku.arch)
    logger.info(
        "Main specs - vCPU: %s, RAM: %s %s, instance storage: %s",
        sku.cpu,
        sku.ram_mb if sku.ram_mb < 1024 else int(sku.ram_mb / 1024),
        "MiB" if sku.ram_mb < 1024 else "GB",
        sku.instance_storage,
    )
    logger.info(
        "Current monthly Spot price in AZ %s: $%s",
        sku.availability_zone,
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
            "Current Spot discount rate in AZ %s: %s%% (spot $%s vs on-demand $%s)",
            sku.availability_zone,
            round(spot_discount, 1),
            sku.monthly_spot_price,
            sku.monthly_ondemand_price,
        )


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

    if not (args.dry_run or args.check_price):
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
    if args.manifest or (args.instance_name or args.check_price):
        if args.manifest:
            env_manifest = try_load_manifest(args.manifest)
        else:
            if args.check_price and not args.instance_name:
                args.instance_name = "price-check"
            env_manifest = get_manifest_from_args(args)
        if not env_manifest:
            logger.exception("Failed to load manifest from CLI args")
            exit(1)
        if args.teardown:  # Delete instance and any attached resources
            env_manifest.expiration_date = "now"

    if args.check_price:
        resolve_manifest_and_display_price(env_manifest, args.manifest_path)
        exit(0)

    cmdb.init_engine_and_check_connection(
        os.path.join(args.config_dir, SQLITE_DBNAME)
    )

    applied_count = schema_manager.do_ddl_rollout_if_needed(
        os.path.join(args.config_dir, SQLITE_DBNAME)
    )
    logger.debug("%s schema migration applied", applied_count)

    if not (args.dry_run or args.check_price or args.check_manifest):
        operator.operator_config_dir = args.config_dir
        clean_up_old_logs_if_any()

    logger.info("Entering main loop")

    operator.do_main_loop(
        cli_env_manifest=env_manifest,
        cli_dry_run=args.dry_run,
        cli_vault_password_file=args.vault_password_file,
        cli_user_manifest_path=args.manifest_path,
        cli_main_loop_interval_s=args.main_loop_interval_s,
        cli_vm_only=args.vm_only,
        cli_destroy_file_base_path=args.destroy_file_base_path,
        cli_teardown=args.teardown,
        cli_connstr_output_only=args.connstr_output_only,
        cli_ansible_path=args.ansible_path,
    )
