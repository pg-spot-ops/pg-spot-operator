import fcntl
import logging
import math
import os.path

import requests
import yaml
from prettytable import PrettyTable
from tap import Tap

from pg_spot_operator import cloud_api, cmdb, manifests, operator
from pg_spot_operator.cloud_impl.aws_client import set_access_keys
from pg_spot_operator.cloud_impl.aws_spot import (
    get_all_active_operator_instances_from_region,
    try_get_monthly_ondemand_price_for_sku,
)
from pg_spot_operator.cloud_impl.cloud_structs import InstanceTypeInfo
from pg_spot_operator.cloud_impl.cloud_util import is_explicit_aws_region_code
from pg_spot_operator.cmdb_impl import schema_manager
from pg_spot_operator.constants import (
    MF_SEC_VM_STORAGE_TYPE_LOCAL,
    SPOT_OPERATOR_EXPIRES_TAG,
    SPOT_OPERATOR_ID_TAG,
)
from pg_spot_operator.instance_type_selection import InstanceTypeSelection
from pg_spot_operator.manifests import InstanceManifest
from pg_spot_operator.operator import clean_up_old_logs_if_any
from pg_spot_operator.util import (
    extract_region_from_az,
    get_aws_region_code_to_name_mapping,
    region_regex_to_actual_region_codes,
    try_download_ansible_from_github,
)

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
    list_regions: bool = str_to_bool(
        os.getenv("PGSO_LIST_REGIONS", "false")
    )  # Display all known AWS region codes + names and exit
    list_instances: bool = str_to_bool(
        os.getenv("PGSO_LIST_INSTANCES", "false")
    )  # List running VMs for given region / region wildcards
    list_strategies: bool = str_to_bool(
        os.getenv("PGSO_LIST_STRATEGIES", "false")
    )  # Display available instance selection strategies and exit
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
    connstr_format: str = os.getenv(
        "PGSO_CONNSTR_FORMAT", "ssh"
    )  # ssh | ansible. Effective currently only when --connstr-output-only and --vm-only set.
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
    postgres_version: int = int(os.getenv("PGSO_POSTGRES_VERSION", "16"))
    instance_types: str = os.getenv(
        "PGSO_INSTANCE_TYPES", ""
    )  # i3.xlarge,i3.2xlarge
    cloud: str = os.getenv("PGSO_CLOUD", "aws")
    region: str = os.getenv(
        "PGSO_REGION", ""
    )  # Exact region or also a Regex in price check mode
    zone: str = os.getenv("PGSO_ZONE", "")
    cpu_min: int = int(os.getenv("PGSO_CPU_MIN", "0"))
    cpu_max: int = int(os.getenv("PGSO_CPU_MAX", "0"))
    selection_strategy: str = os.getenv("PGSO_SELECTION_STRATEGY", "balanced")
    ram_min: int = int(os.getenv("PGSO_RAM_MIN", "0"))
    storage_min: int = int(os.getenv("PGSO_STORAGE_MIN", "0"))
    storage_type: str = os.getenv("PGSO_STORAGE_TYPE", "network")
    storage_speed_class: str = os.getenv(
        "PGSO_STORAGE_SPEED_CLASS", "ssd"
    )  # hdd | ssd | nvme. ssd also includes nvme
    volume_type: str = os.getenv(
        "PGSO_VOLUME_TYPE", "gp3"
    )  # gp2, gp3, io1, io2
    volume_iops: int = int(
        os.getenv("PGSO_VOLUME_IOPS", "0")
    )  # max. gp2/gp3=16K, io1=64K, io2=256K, gp3 def=3K
    volume_throughput: int = int(
        os.getenv("PGSO_VOLUME_THROUGHPUT", "0")
    )  # gp3 def=125, max=1000, relevant only for gp3
    expiration_date: str = os.getenv(
        "PGSO_EXPIRATION_DATE", ""
    )  # ISO 8601 datetime
    self_termination: bool = str_to_bool(
        os.getenv("PGSO_SELF_TERMINATION", "false")
    )
    assign_public_ip: bool = str_to_bool(
        os.getenv("PGSO_ASSIGN_PUBLIC_IP", "true")
    )
    cpu_arch: str = os.getenv("PGSO_CPU_ARCH", "")  # [ arm | x86 ]
    instance_family: str = os.getenv(
        "PGSO_INSTANCE_FAMILY", ""
    )  # Regex, e.g. 'r(6|7)'
    ssh_keys: str = os.getenv("PGSO_SSH_KEYS", "")  # Comma separated
    tuning_profile: str = os.getenv("PGSO_TUNING_PROFILE", "default")
    user_tags: str = os.getenv("PGSO_USER_TAGS", "")  # key=val,key2=val2
    app_db_name: str = os.getenv("PGSO_APP_DB_NAME", "")
    admin_user: str = os.getenv("PGSO_ADMIN_USER", "")
    admin_password: str = os.getenv("PGSO_ADMIN_PASSWORD", "")
    admin_is_superuser: str = os.getenv("PGSO_ADMIN_IS_SUPERUSER", "false")
    os_extra_packages: str = os.getenv(
        "PGSO_OS_EXTRA_PACKAGES", ""
    )  # Comma separated, e.g. postgresql-16-postgis-3,postgresql-16-pgrouting
    shared_preload_libraries: str = os.getenv(
        "PGSO_SHARED_PRELOAD_LIBRARIES", "pg_stat_statements,auth_delay"
    )  # Comma separated
    extensions: str = os.getenv("PGSO_EXTENSIONS", "pg_stat_statements")
    pg_hba_lines: str = os.getenv(
        "PGSO_PG_HBA_LINES", ""
    )  # To override operator default pg_hba access rules. CSV
    aws_access_key_id: str = os.getenv("PGSO_AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("PGSO_AWS_SECRET_ACCESS_KEY", "")
    aws_key_pair_name: str = os.getenv("PGSO_AWS_KEY_PAIR_NAME", "")
    aws_security_group_ids: str = os.getenv(
        "PGSO_AWS_SECURITY_GROUP_IDS", ""
    )  # SG rules are "merged" if multiple provided
    aws_vpc_id: str = os.getenv(
        "PGSO_AWS_VPC_ID", ""
    )  # If not set default VPC in region used
    aws_subnet_id: str = os.getenv("PGSO_AWS_SUBNET_ID", "")
    self_termination_access_key_id: str = os.getenv(
        "PGSO_SELF_TERMINATION_ACCESS_KEY_ID", ""
    )
    self_termination_secret_access_key: str = os.getenv(
        "PGSO_SELF_TERMINATION_SECRET_ACCESS_KEY", ""
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
        region=(
            args.region
            if args.region
            else ".*" if args.check_price else args.vm_host
        ),
        availability_zone=args.zone,
    )

    m.instance_name = args.instance_name
    if not m.region and m.availability_zone:
        m.region = extract_region_from_az(m.availability_zone)
    m.expiration_date = args.expiration_date
    m.assign_public_ip = args.assign_public_ip
    m.setup_finished_callback = args.setup_finished_callback
    m.vm_only = args.vm_only
    m.vm.cpu_arch = args.cpu_arch
    m.vm.cpu_min = args.cpu_min
    m.vm.cpu_max = args.cpu_max
    m.vm.ram_min = args.ram_min
    m.vm.storage_min = args.storage_min
    m.vm.storage_type = args.storage_type
    m.vm.storage_speed_class = args.storage_speed_class.lower()
    m.vm.volume_type = args.volume_type
    m.vm.volume_iops = args.volume_iops
    m.vm.volume_throughput = args.volume_throughput
    if args.instance_types:
        for ins_type in args.instance_types.split(","):
            m.vm.instance_types.append(ins_type)
    m.vm.instance_family = args.instance_family
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
    if args.pg_hba_lines:
        m.postgres.pg_hba_lines = args.pg_hba_lines.split(",")
    m.aws.vpc_id = args.aws_vpc_id
    m.aws.subnet_id = args.aws_subnet_id
    m.aws.access_key_id = args.aws_access_key_id
    m.aws.secret_access_key = args.aws_secret_access_key
    m.aws.key_pair_name = args.aws_key_pair_name
    m.self_termination = args.self_termination
    if args.self_termination:
        m.aws.self_termination_access_key_id = (
            args.self_termination_access_key_id
        )
        m.aws.self_termination_secret_access_key = (
            args.self_termination_secret_access_key
        )
    if args.user_tags:
        for tag_set in args.user_tags.split(","):
            key_val = tag_set.split("=")
            m.user_tags[key_val[0]] = key_val[1]
    m.postgres.version = args.postgres_version
    m.postgres.admin_user = args.admin_user
    m.postgres.admin_password = args.admin_password
    m.postgres.admin_is_superuser = str_to_bool(args.admin_is_superuser)
    m.postgres.app_db_name = args.app_db_name
    m.postgres.tuning_profile = args.tuning_profile
    if args.shared_preload_libraries:
        m.postgres.config_lines["shared_preload_libraries"] = (
            args.shared_preload_libraries
        )
    if args.extensions:
        m.postgres.extensions = args.extensions.strip().split(",")
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
    if args.list_instances:
        if not args.region:
            logger.error(
                "--region input expected. Can be fuzzy / regex",
            )
            exit(1)
        return

    if not fixed_vm:
        if not args.region and not args.zone and not args.check_price:
            logger.error("--region input expected")
            exit(1)
        if not args.instance_name and not (
            args.check_price or args.teardown_region
        ):
            logger.error("--instance-name input expected")
            exit(1)
        if (
            args.storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL
            and not args.storage_min
            and not (args.teardown or args.teardown_region)
        ):
            logger.error(
                "--storage-min input expected for --storage-type=local"
            )
            exit(1)
        if (
            not (args.teardown or args.teardown_region)
            and not args.check_price
            and not args.storage_min
        ):
            logger.error("--storage-min input expected")
            exit(1)
        if (
            args.region
            and not args.check_price
            and len(args.region.split("-")) != 3
        ):
            logger.error(
                """Unexpected --region format, run --list-regions for a complete region listing""",
            )
            exit(1)
        if args.zone and len(args.zone.split("-")) not in (3, 5):
            logger.error(
                """Unexpected --zone format, expecting smth like: eu-west-1b or us-west-2-lax-1a""",
            )
            exit(1)
    if args.teardown_region and (
        not args.region or len(args.region.split("-")) != 3
    ):
        logger.error(
            """--teardown-region requires explicit --region set""",
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
    if args.admin_user or args.admin_password:
        if not (args.admin_user and args.admin_password):
            logger.error(
                "Both --admin-user / --admin-password need to be provided",
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
    if args.self_termination and not args.expiration_date:
        logger.error(
            "--self-termination assumes also --expiration-date set",
        )
        exit(1)
    if args.self_termination and not (
        args.self_termination_access_key_id
        and args.self_termination_secret_access_key
    ):
        logger.error(
            "Self-termination on expiration date requires --self-termination-access-key-id and --self-termination-secret-access-key",
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
    if not (
        args.check_price or args.vm_host
    ) and not is_explicit_aws_region_code(args.region):
        logger.error(
            "Fuzzy or regex --region input only allowed in --check-price mode",
        )
        exit(1)
    if (
        args.selection_strategy
        not in InstanceTypeSelection.get_strategies_with_descriptions()
    ):
        logger.error(
            "Invalid --selection-strategy input",
        )
        list_strategies_and_exit()
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
        logger.error("Failed to get / compile manifest")
        exit(1)

    m.model_validate(m)
    logger.debug("Pydantic model_validate() OK")
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


def display_selected_skus_for_region(
    selected_skus: list[InstanceTypeInfo],
) -> None:
    table: list[list] = [
        [
            "Region",
            "SKU",
            "Arch",
            "vCPU",
            "RAM",
            "Instance storage",
            "Spot $ (Mo)",
            "On-Demand $ (Mo)",
            "EC2 discount",
            "Approx. RDS win",
            "Evic. rate (Mo)",
        ]
    ]
    ec2_discount_rate = "N/A"
    approx_rds_x = "N/A"
    for i in selected_skus:
        if not i.monthly_ondemand_price:
            i.monthly_ondemand_price = try_get_monthly_ondemand_price_for_sku(
                i.region, i.instance_type
            )
        if i.monthly_ondemand_price and i.monthly_spot_price:
            ec2_discount_rate = str(
                round(
                    100.0
                    * (i.monthly_spot_price - i.monthly_ondemand_price)
                    / i.monthly_ondemand_price
                )
            )
            approx_rds_x_int = math.ceil(
                i.monthly_ondemand_price / i.monthly_spot_price * 1.5
            )
            approx_rds_x = f"{approx_rds_x_int}x"

        max_reg_len = max([len(x.region) for x in selected_skus])
        max_sku_len = max([len(x.instance_type) for x in selected_skus])
        max_inst_stor_len = max(
            [
                len(
                    f"{x.instance_storage} GB {x.storage_speed_class}"
                    if x.instance_storage
                    else "EBS only"
                )
                for x in selected_skus
            ]
        )
        ram_gb = round(i.ram_mb / 1024)
        table.append(
            [
                i.region.ljust(max_reg_len, " "),
                i.instance_type.ljust(max_sku_len, " "),
                i.arch,
                i.cpu,
                f"{ram_gb} GB",
                (
                    f"{i.instance_storage} GB {i.storage_speed_class}"
                    if i.instance_storage
                    else "EBS only"
                ).ljust(max_inst_stor_len),
                f"{i.monthly_spot_price}",
                f"{i.monthly_ondemand_price}",
                f"{ec2_discount_rate}%",
                approx_rds_x,
                (
                    i.eviction_rate_group_label
                    if i.eviction_rate_group_label
                    else "N/A"
                ),
            ]
        )

    tab = PrettyTable(table[0])
    tab.add_rows(table[1:])
    print(tab)


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
        "Resolving HW requirements to actual instance types / prices using --selection-strategy=%s ...",
        m.vm.instance_selection_strategy,
    )

    use_boto3: bool = False
    # Set AWS creds if AZ set, AZ-specific pricing info not available over static API
    if m.availability_zone or (
        (m.aws.access_key_id and m.aws.secret_access_key) or m.aws.profile_name
    ):
        m.decrypt_secrets_if_any()
        set_access_keys(
            m.aws.access_key_id, m.aws.secret_access_key, m.aws.profile_name
        )
        use_boto3 = True

    if is_explicit_aws_region_code(m.region):
        regions = [m.region]
    else:
        regions = region_regex_to_actual_region_codes(m.region)
        if not regions:
            logger.error(
                "Could not resolve region regex '%s' to any regions", m.region
            )
            exit(1)
        logger.info(
            "Regions in consideration based on --region='%s' input: %s",
            m.region,
            regions,
        )

    selected_skus = cloud_api.resolve_hardware_requirements_to_instance_types(
        m, use_boto3=use_boto3, regions=regions
    )

    if not selected_skus:
        logger.error(
            f"No SKUs matching HW requirements found for instance {m.instance_name} in region / zone {m.region or m.availability_zone}"
        )
        exit(1)

    # Do an extra sort in case have multi-regions or "random" strategy
    instance_selection_strategy_cls = (
        InstanceTypeSelection.get_selection_strategy("cheapest")
    )
    logger.debug(
        "Applying extra sorting using strategy %s over %s instances from all regions ...",
        "cheapest",
        len(selected_skus),
    )

    selected_skus = instance_selection_strategy_cls.execute(selected_skus)
    if len(selected_skus) > 10:
        selected_skus = selected_skus[:10]

    logger.info(
        "Top cheapest instances found for strategy '%s' (to list available strategies run --list-strategies / PGSO_LIST_STRATEGIES=y):",
        m.vm.instance_selection_strategy,
    )

    display_selected_skus_for_region(selected_skus)

    return


def download_ansible_from_github_if_not_set_locally(
    args: ArgumentParser,
) -> None:
    if (
        args.ansible_path
        or args.check_price
        or args.vm_only
        or args.check_manifest
        or args.teardown
        or args.teardown_region
        or os.path.exists("./ansible")
    ):
        return

    # Written after successful Ansible DL from a tag
    local_ansible_release_tag_file_path = os.path.expanduser(
        os.path.join(args.config_dir, "ansible", "release_tag")
    )

    # If no release_tag file but setup file exists probably user pre-downloaded Ansible.
    # Leaves a slight chance for a race condition though when we DL but crash before writing the release_tag file, but good enough probably for now...
    if os.path.exists(
        os.path.expanduser(
            os.path.join(
                args.config_dir, "ansible", "v1/single_instance_setup.yml"
            )
        )
    ) and not os.path.exists(local_ansible_release_tag_file_path):
        logger.info(
            "Assuming manually downloaded Ansible files in %s as release_tag not found (remove the folder to auto re-download)",
            os.path.join(args.config_dir, "ansible"),
        )
        return

    target_tag: str = ""
    zip_url: str = ""

    try:  # If installed via pip/pipx can read out the version easily
        from importlib.metadata import version

        pkg_ver = version("pg-spot-operator")
        if pkg_ver:
            logger.debug(
                "Package version %s identified via importlib.metadata.version",
                pkg_ver,
            )
            target_tag = pkg_ver
            zip_url = f"https://github.com/pg-spot-ops/pg-spot-operator/archive/refs/tags/{pkg_ver}.zip"
    except Exception:
        logger.debug(
            "Failed to inquiry package version via importlib.metadata.version"
        )

    if (
        not zip_url
    ):  # Let's try to fetch the latest tag directly from the Github API
        url = "https://api.github.com/repos/pg-spot-ops/pg-spot-operator/releases/latest"
        try:
            f = requests.get(
                url, headers={"Content-Type": "application/json"}, timeout=5
            )
            if f.status_code != 200:
                logger.debug(
                    "Failed to retrieve Github repo releases listing - retcode: %s, URL: %s",
                    f.status_code,
                    url,
                )
            data = f.json()
            if data.get("tag_name"):
                target_tag = data["tag_name"]
                zip_url = f"https://github.com/pg-spot-ops/pg-spot-operator/archive/refs/tags/{target_tag}.zip"
        except Exception as e:
            logger.debug(
                "Failed to retrieve Github repo releases listing from %s. Error: %s",
                url,
                e,
            )

    if (
        not target_tag
    ):  # Check if tag already downloaded, "main" always re-downloaded
        target_tag = "main"
        zip_url = "https://github.com/pg-spot-ops/pg-spot-operator/archive/refs/heads/main.zip"

    if os.path.exists(local_ansible_release_tag_file_path):
        try:
            currently_dl_ver = (
                open(local_ansible_release_tag_file_path).read().strip()
            )
            if (
                currently_dl_ver == target_tag
                and target_tag != "main"
                and os.path.exists(
                    os.path.expanduser(
                        os.path.join(
                            args.config_dir,
                            "ansible",
                            "v1/single_instance_setup.yml",
                        )
                    )
                )
            ):
                logger.info(
                    "Found Ansible files for tag %s from %s",
                    target_tag,
                    os.path.join(args.config_dir, "ansible"),
                )
                return
        except Exception:
            logger.debug(
                "Failed to read path %s",
                local_ansible_release_tag_file_path,
            )

    # Download or re-download if could not determine a tag
    dl_ok = try_download_ansible_from_github(
        target_tag,
        zip_url,
        args.config_dir,
    )
    if not dl_ok:
        logger.error(
            "--ansible-path not set, cwd .ansible dir not found and also failed to download from Github, cannot proceed"
        )
        exit(1)

    with open(local_ansible_release_tag_file_path, "w") as fp:
        fp.write(target_tag)

    logger.debug(
        "Setting --ansible-path to %s",
        os.path.join(args.config_dir, "ansible"),
    )
    args.ansible_path = os.path.join(args.config_dir, "ansible")


def init_cmdb_and_apply_schema_migrations_if_needed(
    args: ArgumentParser,
) -> None:
    cmdb.init_engine_and_check_connection(
        os.path.join(args.config_dir, SQLITE_DBNAME)
    )
    applied_count = schema_manager.do_ddl_rollout_if_needed(
        os.path.join(args.config_dir, SQLITE_DBNAME)
    )
    logger.debug("%s schema migration applied", applied_count)


def list_regions_and_exit() -> None:
    print(
        "# Based on: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-regions-availability-zones.html#concepts-available-regions"
    )
    for code, location_name in sorted(
        get_aws_region_code_to_name_mapping().items()
    ):
        print(f"{code}\t\t{location_name}")
    exit(0)


def list_strategies_and_exit() -> None:
    print("Available --selection-strategy / PGSO_SELECTION_STRATEGY values:\n")
    for (
        strategy,
        description,
    ) in InstanceTypeSelection.get_strategies_with_descriptions().items():
        print(f"{strategy.ljust(20)}: {description}")
    print()
    exit(0)


def list_instances_and_exit(args: ArgumentParser) -> None:
    regions = region_regex_to_actual_region_codes(args.region)
    if not regions:
        logger.error("No regions provided")
        exit(1)

    errors = 0
    instances: list[dict] = []

    for reg in regions:
        logger.info(
            "Fetching non-terminated pg-spot-operator instances for region '%s' ...",
            reg,
        )
        try:
            instance_descriptions = (
                get_all_active_operator_instances_from_region(reg)
            )
            logger.info("Instances found: %s", len(instance_descriptions))
            if instance_descriptions:
                instances.extend(instance_descriptions)
        except Exception:
            logger.error("Failed to complete scan for region %s", reg)
            errors += 1

    cols = [
        "Instance name",
        "AZ",
        "InstanceId",
        "InstanceType",
        "vCPU",
        "VolumeId",
        "LaunchTime",
        "PrivateIpAddress",
        "PublicIpAddress",
        "VpcId",
        "Expiration Date",
    ]
    tab = PrettyTable(cols)
    for i in instances:
        tags_as_dict = {tag["Key"]: tag["Value"] for tag in i.get("Tags", [])}
        tab.add_row(
            [
                tags_as_dict.get(SPOT_OPERATOR_ID_TAG),
                i.get("Placement", {}).get("AvailabilityZone"),
                i.get("InstanceId"),
                i.get("InstanceType"),
                i.get("CpuOptions", {}).get("CoreCount"),
                (
                    i["BlockDeviceMappings"][1].get("Ebs", {}).get("VolumeId")
                    if len(i.get("BlockDeviceMappings", [])) > 1
                    else None
                ),
                i.get("LaunchTime"),
                i.get("PrivateIpAddress"),
                i.get("PublicIpAddress"),
                i.get("VpcId"),
                tags_as_dict.get(SPOT_OPERATOR_EXPIRES_TAG),
            ]
        )

    print(tab)

    exit(errors)


def main():  # pragma: no cover

    global args
    args = validate_and_parse_args()

    logging.basicConfig(
        format=(
            "%(message)s"
            if (args.check_price or args.list_instances)
            else (
                "%(asctime)s %(levelname)s %(threadName)s %(filename)s:%(lineno)d %(message)s"
                if args.verbose
                else "%(asctime)s %(levelname)s %(message)s"
            )
        ),
        level=(logging.DEBUG if args.verbose else logging.INFO),
    )

    if args.show_help:
        args.print_help()
        exit(0)

    if args.list_regions:
        list_regions_and_exit()

    if args.list_strategies:
        list_strategies_and_exit()

    if args.check_manifest:
        check_manifest_and_exit(args)

    if not (args.manifest_path or args.manifest):
        check_cli_args_valid(args)

    if args.list_instances:
        list_instances_and_exit(args)

    logger.debug("Args: %s", args.as_dict()) if args.verbose else None

    if not (args.dry_run or args.check_price):
        ensure_single_instance_running(args.instance_name)

    if args.teardown_region:
        if not args.dry_run:
            try:
                init_cmdb_and_apply_schema_migrations_if_needed(args)
            except Exception:
                logger.error(
                    "Could not initialize CMDB, can't mark instances as deleted"
                )
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

    init_cmdb_and_apply_schema_migrations_if_needed(args)

    if not (args.dry_run or args.check_price or args.check_manifest):
        operator.operator_config_dir = args.config_dir
        clean_up_old_logs_if_any()

    # Download the Ansible scripts if missing and in some "real" mode, as not bundled to PyPI currently
    download_ansible_from_github_if_not_set_locally(args)

    logger.debug("Entering main loop")

    operator.do_main_loop(
        cli_env_manifest=env_manifest,
        cli_dry_run=args.dry_run,
        cli_vault_password_file=args.vault_password_file,
        cli_user_manifest_path=args.manifest_path,
        cli_main_loop_interval_s=args.main_loop_interval_s,
        cli_destroy_file_base_path=args.destroy_file_base_path,
        cli_teardown=args.teardown,
        cli_connstr_output_only=args.connstr_output_only,
        cli_connstr_format=args.connstr_format,
        cli_ansible_path=args.ansible_path,
    )
