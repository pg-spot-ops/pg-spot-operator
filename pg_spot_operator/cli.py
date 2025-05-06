import fcntl
import logging
import os.path
import re
import shutil

import humanize
import requests
import yaml
from prettytable import PrettyTable
from tap import Tap

from pg_spot_operator import cloud_api, cmdb, manifests, operator
from pg_spot_operator.cloud_api import get_spot_pricing_summary_for_region
from pg_spot_operator.cloud_impl.aws_client import set_access_keys
from pg_spot_operator.cloud_impl.aws_spot import (
    get_all_active_operator_instances_from_region,
    get_current_hourly_spot_price_static,
    try_get_monthly_ondemand_price_for_sku,
)
from pg_spot_operator.cloud_impl.aws_vm import (
    get_operator_volumes_in_region_full,
)
from pg_spot_operator.cloud_impl.cloud_structs import (
    InstanceTypeInfo,
    RegionalSpotPricingStats,
)
from pg_spot_operator.cloud_impl.cloud_util import (
    add_aws_tags_dict_from_list_tags,
    is_explicit_aws_region_code,
    resolve_regions_from_fuzzy_input,
)
from pg_spot_operator.cmdb_impl import schema_manager
from pg_spot_operator.constants import (
    ALL_ENABLED_REGIONS,
    BACKUP_TYPE_NONE,
    CONNSTR_FORMAT_AUTO,
    DEFAULT_SSH_PUBKEY_PATH,
    DEFAULT_VM_LOGIN_USER,
    MF_SEC_VM_STORAGE_TYPE_LOCAL,
    SPOT_OPERATOR_EXPIRES_TAG,
    SPOT_OPERATOR_ID_TAG,
)
from pg_spot_operator.instance_type_selection import (
    SELECTION_STRATEGY_RANDOM,
    InstanceTypeSelection,
)
from pg_spot_operator.manifests import InstanceManifest
from pg_spot_operator.operator import clean_up_old_logs_if_any
from pg_spot_operator.pgtuner import TUNING_PROFILES
from pg_spot_operator.util import (
    calc_discount_rate_str,
    check_default_ssh_key_exists_and_readable,
    extract_mtf_months_from_eviction_rate_group_label,
    extract_region_from_az,
    get_aws_region_code_to_name_mapping,
    region_regex_to_actual_region_codes,
    timestamp_to_human_readable_delta,
    try_download_ansible_from_github,
    utc_datetime_to_local_time_zone,
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


def str_boolean_false_to_empty_string(param: str) -> str:
    if not param:
        return ""
    if param.strip().lower()[0] == "f" or param.strip().lower()[0] == "n":
        return ""
    if param.strip().lower() == "off":
        return ""
    if param.strip().lower() == "0":
        return ""
    if param.strip().lower() == "disabled":
        return ""
    return param


class ArgumentParser(Tap):
    manifest_path: str = os.getenv("MANIFEST_PATH", "")  # User manifest path
    ansible_path: str = os.getenv(
        "ANSIBLE_PATH", ""
    )  # Use a non-default Ansible path
    main_loop_interval_s: int = int(
        os.getenv("MAIN_LOOP_INTERVAL_S")
        or 60  # Increase if causing too many calls to the cloud API
    )
    config_dir: str = os.getenv(
        "CONFIG_DIR", "~/.pg-spot-operator"
    )  # For internal state keeping
    vault_password_file: str = os.getenv(
        "VAULT_PASSWORD_FILE", ""
    )  # Can also be set on instance level
    verbose: bool = str_to_bool(os.getenv("VERBOSE", "false"))  # More chat
    check_price: bool = str_to_bool(
        os.getenv("CHECK_PRICE", "false")
    )  # Resolve HW reqs, show Spot price and exit
    list_regions: bool = str_to_bool(
        os.getenv("LIST_REGIONS", "false")
    )  # Display all known AWS region codes + names and exit
    list_avg_spot_savings: bool = str_to_bool(
        os.getenv("LIST_AVG_SPOT_SAVINGS", "false")
    )  # Display avg. regional Spot savings and eviction rates to choose the best region. Can apply the --region filter.
    list_instances: bool = str_to_bool(
        os.getenv("LIST_INSTANCES", "false")
    )  # List running VMs for given region / region wildcards
    list_instances_cmdb: bool = str_to_bool(
        os.getenv("LIST_INSTANCES_CMDB", "false")
    )  # List non-deleted instances from CMDB for all regions
    list_strategies: bool = str_to_bool(
        os.getenv("LIST_STRATEGIES", "false")
    )  # Display available instance selection strategies and exit
    list_vm_creates: bool = str_to_bool(
        os.getenv("LIST_VM_CREATES", "false")
    )  # Show VM provisioning times for active instances. Region / instance name filtering applies
    check_manifest: bool = str_to_bool(
        os.getenv("CHECK_MANIFEST", "false")
    )  # Validate instance manifests and exit
    dry_run: bool = str_to_bool(
        os.getenv("DRY_RUN", "false")
    )  # Just resolve the VM instance type
    debug: bool = str_to_bool(
        os.getenv("DEBUG", "false")
    )  # Don't clean up Ansible run files plus extra developer outputs
    vm_only: bool = str_to_bool(
        os.getenv("VM_ONLY", "false")
    )  # No Ansible / Postgres setup
    no_mount_disks: bool = str_to_bool(
        os.getenv("NO_MOUNT_DISKS", "false")
    )  # Skip data disks mounting via Ansible. Relevant only is --vm-only set
    persistent_vms: bool = str_to_bool(
        os.getenv("PERSISTENT_VMS", "false")
    )  # Use persistent VMs instead of Spot
    connstr_only: bool = str_to_bool(
        os.getenv("CONNSTR_ONLY", "false")
    )  # Set up Postgres, print connstr and exit
    connstr_format: str = os.getenv(
        "CONNSTR_FORMAT", CONNSTR_FORMAT_AUTO
    )  # auto = "postgres" if admin user / password set, otherwise "ssh". [auto | ssh | ansible | postgres]
    manifest: str = os.getenv("MANIFEST", "")  # Manifest to process
    stop: bool = str_to_bool(
        os.getenv("STOP", "false")
    )  # Stop the VM but leave disks around for a later resume / teardown
    resume: bool = str_to_bool(
        os.getenv("RESUME", "false")
    )  # Resurrect the input --instance-name using last known settings
    teardown: bool = str_to_bool(
        os.getenv("TEARDOWN", "false")
    )  # Delete VM and other created resources
    teardown_region: bool = str_to_bool(
        os.getenv("TEARDOWN_REGION", "false")
    )  # Delete all operator tagged resources in region
    instance_name: str = os.getenv(
        "INSTANCE_NAME", ""
    )  # If set other below params become relevant
    postgres_version: int = int(os.getenv("POSTGRES_VERSION", "17"))
    instance_types: str = os.getenv(
        "INSTANCE_TYPES", ""
    )  # i3.xlarge,i3.2xlarge
    cloud: str = os.getenv("CLOUD", "aws")
    region: str = os.getenv(
        "REGION", ""
    )  # Exact region or also a Regex in price check mode
    zone: str = os.getenv("ZONE", "")
    max_price: float = float(os.getenv("MAX_PRICE", "0"))  # Max hourly price
    cpu_min: int = int(os.getenv("CPU_MIN", "0"))
    cpu_max: int = int(os.getenv("CPU_MAX", "0"))
    allow_burstable: bool = str_to_bool(
        os.getenv("ALLOW_BURSTABLE", "false")
    )  # Allow t-class instance types
    selection_strategy: str = os.getenv("SELECTION_STRATEGY", "balanced")
    ram_min: int = int(os.getenv("RAM_MIN", "1"))  # In GB
    ram_max: int = int(os.getenv("RAM_MAX", "0"))  # In GB
    storage_min: int = int(
        os.getenv("STORAGE_MIN", "0")
    )  # In GB. Precise provisioning size for network volumes, minimum for --storage-type=local
    storage_type: str = os.getenv("STORAGE_TYPE", "network")
    storage_speed_class: str = os.getenv(
        "STORAGE_SPEED_CLASS", "ssd"
    )  # hdd | ssd | nvme. ssd also includes nvme
    os_disk_size: int = int(os.getenv("OS_DISK_SIZE", "20"))
    volume_type: str = os.getenv(
        "VOLUME_TYPE", "gp3"
    )  # gp2, gp3, io1, io2, st1, sc1
    volume_iops: int = int(
        os.getenv("VOLUME_IOPS", "0")
    )  # max. gp2/gp3=16K, io1=64K, io2=256K, gp3 def=3K
    volume_throughput: int = int(
        os.getenv("VOLUME_THROUGHPUT", "0")
    )  # gp3 def=125, max=1000, relevant only for gp3
    stripes: int = int(
        os.getenv("STRIPES", "1")
    )  # 1-28 stripe volumes allowed. Default is 1, i.e. no striping
    stripe_size_kb: int = int(
        os.getenv("STRIPE_SIZE_KB", "64")
    )  # Stripe size in KB. 64kB is LVM2 default
    expiration_date: str = os.getenv(
        "EXPIRATION_DATE", ""
    )  # ISO 8601 datetime, optionally with time zone
    self_termination: bool = str_to_bool(
        os.getenv("SELF_TERMINATION", "false")
    )
    private_ip_only: bool = str_to_bool(
        os.getenv("PRIVATE_IP_ONLY", "false")
    )  # Public IPs (default mode) cost ~$4 a month
    static_ip_addresses: bool = str_to_bool(
        os.getenv("STATIC_IP_ADDRESSES", "false")
    )  # If set and in Public IP mode then a fixed Elastic IP is assigned (has limited availability on account level)
    cpu_arch: str = os.getenv("CPU_ARCH", "")  # [ arm | x86 ]
    instance_family: str = os.getenv(
        "INSTANCE_FAMILY", ""
    )  # Regex, e.g. 'r(6|7)'
    ssh_keys: str = os.getenv("SSH_KEYS", "")  # Comma separated
    tuning_profile: str = os.getenv("TUNING_PROFILE", "default")
    user_tags: str = os.getenv("USER_TAGS", "")  # key=val,key2=val2
    app_db_name: str = os.getenv("APP_DB_NAME", "")
    admin_user: str = os.getenv("ADMIN_USER", "")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    admin_is_superuser: str = os.getenv("ADMIN_IS_SUPERUSER", "false")
    os_extra_packages: str = os.getenv(
        "OS_EXTRA_PACKAGES", ""
    )  # Comma separated, e.g. postgresql-16-postgis-3,postgresql-16-pgrouting
    shared_preload_libraries: str = os.getenv(
        "SHARED_PRELOAD_LIBRARIES", "pg_stat_statements,auth_delay"
    )  # Comma separated
    extensions: str = os.getenv("EXTENSIONS", "pg_stat_statements")
    pg_hba_lines: str = os.getenv(
        "PG_HBA_LINES", ""
    )  # To override operator default pg_hba access rules. CSV
    aws_access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    aws_key_pair_name: str = os.getenv("AWS_KEY_PAIR_NAME", "")
    aws_security_group_ids: str = os.getenv(
        "AWS_SECURITY_GROUP_IDS", ""
    )  # SG rules are "merged" if multiple provided
    aws_vpc_id: str = os.getenv(
        "AWS_VPC_ID", ""
    )  # If not set default VPC in region used
    aws_subnet_id: str = os.getenv("AWS_SUBNET_ID", "")
    self_termination_access_key_id: str = os.getenv(
        "SELF_TERMINATION_ACCESS_KEY_ID", ""
    )
    self_termination_secret_access_key: str = os.getenv(
        "SELF_TERMINATION_SECRET_ACCESS_KEY", ""
    )
    vm_host: str = os.getenv(
        "VM_HOST", ""
    )  # Skip creation and use the provided IP
    vm_login_user: str = os.getenv(
        "VM_LOGIN_USER", DEFAULT_VM_LOGIN_USER
    )  # Default SSH key will be used
    destroy_file_base_path: str = os.getenv(
        "DESTROY_FILE_BASE_PATH", "/tmp/destroy-"
    )  # If a file named base+instance detected, the instance is expired and the program exits
    setup_finished_callback: str = os.getenv(
        "SETUP_FINISHED_CALLBACK", ""
    )  # An optional executable to propagate the connect string somewhere. Gets connect details as input parameters
    connstr_output_path: str = os.getenv(
        "CONNSTR_OUTPUT_PATH", ""
    )  # When set write Postgres (or SSH if --vm-only) connect string into a file
    connstr_bucket: str = os.getenv(
        "CONNSTR_BUCKET", ""
    )  # An S3 bucket to write the connect string into
    connstr_bucket_key: str = os.getenv(
        "CONNSTR_BUCKET_KEY", ""
    )  # Required if --connstr-bucket set
    connstr_bucket_region: str = os.getenv("CONNSTR_BUCKET_REGION", "")
    connstr_bucket_endpoint: str = os.getenv(
        "CONNSTR_BUCKET_ENDPOINT", ""
    )  # e.g. https://myminio:9000
    connstr_bucket_access_key: str = os.getenv("CONNSTR_BUCKET_ACCESS_KEY", "")
    connstr_bucket_access_secret: str = os.getenv(
        "CONNSTR_BUCKET_ACCESS_SECRET", ""
    )
    backup_s3_bucket: str = os.getenv(
        "BACKUP_S3_BUCKET", ""
    )  # If set, pgbackrest will be configured
    backup_cipher: str = os.getenv(
        "BACKUP_CIPHER", ""
    )  # pgbackrest cipher password
    backup_retention_days: int = int(os.getenv("BACKUP_RETENTION_DAYS", "1"))
    backup_s3_key: str = os.getenv("BACKUP_S3_KEY", "")
    backup_s3_key_secret: str = os.getenv("BACKUP_S3_KEY_SECRET", "")
    monitoring: bool = str_to_bool(os.getenv("MONITORING", "false"))
    grafana_externally_accessible: bool = str_to_bool(
        os.getenv("GRAFANA_EXTERNALLY_ACCESSIBLE", "true")
    )
    grafana_anonymous: bool = str_to_bool(
        os.getenv("GRAFANA_ANONYMOUS", "true")
    )
    ssh_private_key: str = os.getenv(
        "SSH_PRIVATE_KEY", ""
    )  # To use a non-default (~/.ssh/id_rsa) SSH key


args: ArgumentParser | None = None


def validate_and_parse_args() -> ArgumentParser:
    args = ArgumentParser(
        prog="pg-spot-operator",
        description="Maintains Postgres on Spot VMs",
        underscores_to_dashes=True,
    ).parse_args()

    return args


def running_in_check_or_list_mode(args: ArgumentParser) -> bool:
    return (
        args.check_price
        or args.list_instances
        or args.list_instances_cmdb
        or args.list_regions
        or args.list_strategies
        or args.list_avg_spot_savings
        or args.list_vm_creates
        or args.check_manifest
    )


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
            else ALL_ENABLED_REGIONS if args.check_price else args.vm_host
        ),
        availability_zone=args.zone,
    )

    m.instance_name = args.instance_name
    if not m.region and m.availability_zone:
        m.region = extract_region_from_az(m.availability_zone)
    m.vm.persistent_vms = args.persistent_vms
    m.expiration_date = args.expiration_date
    m.private_ip_only = args.private_ip_only
    m.static_ip_addresses = args.static_ip_addresses
    m.integrations.setup_finished_callback = args.setup_finished_callback
    m.integrations.connstr_bucket = args.connstr_bucket
    m.integrations.connstr_bucket_filename = args.connstr_bucket_key
    m.integrations.connstr_bucket_region = args.connstr_bucket_region
    m.integrations.connstr_bucket_endpoint = args.connstr_bucket_endpoint
    m.integrations.connstr_bucket_key = args.connstr_bucket_access_key
    m.integrations.connstr_bucket_secret = args.connstr_bucket_access_secret
    m.vm_only = args.vm_only
    m.no_mount_disks = args.no_mount_disks
    m.vm.cpu_arch = args.cpu_arch
    m.vm.max_price = args.max_price
    m.vm.cpu_min = args.cpu_min
    m.vm.cpu_max = args.cpu_max
    m.vm.allow_burstable = args.allow_burstable
    m.vm.ram_min = args.ram_min
    m.vm.ram_max = args.ram_max
    m.vm.os_disk_size = args.os_disk_size
    m.vm.storage_min = args.storage_min
    m.vm.storage_type = args.storage_type
    m.vm.storage_speed_class = args.storage_speed_class.lower()
    m.vm.volume_type = args.volume_type
    m.vm.volume_iops = args.volume_iops
    m.vm.volume_throughput = args.volume_throughput
    m.vm.stripes = args.stripes
    m.vm.stripe_size_kb = args.stripe_size_kb
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
        m.monitoring.pgwatch.enabled = True
        m.monitoring.grafana.enabled = True
        m.monitoring.grafana.anonymous_access = args.grafana_anonymous
        m.monitoring.grafana.externally_accessible = (
            args.grafana_externally_accessible
        )

    m.ansible.private_key = args.ssh_private_key

    m.original_manifest = yaml.dump(
        m.model_dump(exclude_none=True, exclude_defaults=True)
    )

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


def need_ssh_access(a: ArgumentParser) -> bool:
    return not (
        a.check_price
        or a.check_manifest
        or a.list_instances
        or a.list_instances_cmdb
        or a.list_regions
        or a.list_strategies
        or a.list_avg_spot_savings
        or a.list_vm_creates
        or a.dry_run
        or a.teardown
        or a.teardown_region
    )


def check_cli_args_valid(args: ArgumentParser):
    fixed_vm = bool(args.vm_login_user and args.vm_host)

    if args.tuning_profile and args.tuning_profile not in TUNING_PROFILES:
        logger.error(
            "Invalid --tuning-profile %s. Available profiles: %s",
            args.tuning_profile,
            TUNING_PROFILES,
        )
        exit(1)

    if (
        need_ssh_access(args)
        and not (
            args.ssh_private_key or args.aws_key_pair_name or args.ssh_keys
        )
        and not check_default_ssh_key_exists_and_readable()
    ):
        logger.warning(
            "No SSH access keys provided / found (%s) - might not be able to access the VM later. Relevant flags: --ssh-keys, --ssh-private-key, --aws-key-pair-name",
            DEFAULT_SSH_PUBKEY_PATH,
        )

    if not fixed_vm:
        if not (args.region or args.zone) and not (
            args.check_price
            or args.list_instances
            or args.list_instances_cmdb
            or args.list_vm_creates
            or args.stop
            or args.resume
            or args.teardown
        ):
            logger.error("--region input expected")
            exit(1)
        if not args.instance_name and not (
            running_in_check_or_list_mode(args) or args.teardown_region
        ):
            logger.error("--instance-name input expected")
            exit(1)
        if (
            args.storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL
            and not args.storage_min
            and not (args.teardown or args.teardown_region or args.resume)
        ):
            logger.error(
                "--storage-min input expected for --storage-type=local"
            )
            exit(1)
        if (
            (
                not running_in_check_or_list_mode(args)
                or (
                    running_in_check_or_list_mode(args)
                    and args.storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL
                )
            )
            and not args.storage_min
            and not (
                args.teardown
                or args.teardown_region
                or args.stop
                or args.resume
            )
        ):
            logger.error("--storage-min input expected")
            exit(1)
        if (
            args.region
            and not (
                args.check_price
                or args.list_instances
                or args.list_instances_cmdb
                or args.list_vm_creates
            )
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
        if args.volume_type in ("st1", "sc1") and args.storage_min < 125:
            logger.error("st1 / sc1 volumes must be at least 125 GiB in size")
            exit(1)
        if args.volume_type in ("st1", "sc1") and (
            args.volume_iops or args.volume_throughput
        ):
            logger.error(
                "Provisioned throughput / iops not supported for st1 / sc1 volumes"
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
        args.check_price
        or args.list_instances
        or args.list_instances_cmdb
        or args.list_vm_creates
        or args.vm_host
        or args.stop
        or args.resume
        or args.teardown
    ) and not is_explicit_aws_region_code(args.region):
        logger.error(
            "Fuzzy or regex --region input only allowed in --check-price and --list-* modes",
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
    if (args.stop or args.resume or args.teardown) and not args.region:
        args.region = "auto"


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
            "Local storage",
            "$ Spot",
            "$ On-Demand",
            "Discount (%)",
            "Evic. rate",
        ]
    ]

    for i in selected_skus:
        if not i.monthly_ondemand_price:
            i.monthly_ondemand_price = try_get_monthly_ondemand_price_for_sku(
                i.region, i.instance_type
            )

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
                f"{i.monthly_spot_price} ({i.hourly_spot_price}/h)",
                f"{i.monthly_ondemand_price} ({i.hourly_ondemand_price}/h)",
                calc_discount_rate_str(
                    i.monthly_spot_price, i.monthly_ondemand_price
                ),
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

    # Selection strategies are relevant only when using Spot VMs
    logger.info(
        "Resolving HW requirements to actual instance types / prices %s ...",
        (
            ""
            if m.vm.persistent_vms
            else f"using --selection-strategy={m.vm.instance_selection_strategy}"
        ),
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

    regions = resolve_regions_from_fuzzy_input(m.region)

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

    if (
        len(regions) > 1
        or m.vm.instance_selection_strategy == SELECTION_STRATEGY_RANDOM
    ):
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

    if m.vm.persistent_vms:
        logger.info("Top cheapest instances by ondemand price:")
    else:
        logger.info(
            "Top cheapest instances found for strategy '%s' (to list available strategies run --list-strategies / LIST_STRATEGIES=y):",
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
        "\n# PS Note that not all regions might not be available / enabled for an account! To list available regions via the AWS CLI:"
        "\n# aws ec2 describe-regions --filter Name=opt-in-status,Values=opted-in,opt-in-not-required --query 'Regions[*].[RegionName]' --output text"
    )
    for code, location_name in sorted(
        get_aws_region_code_to_name_mapping().items()
    ):
        print(f"{code}\t\t{location_name}")
    exit(0)


def list_strategies_and_exit() -> None:
    print("Available --selection-strategy / SELECTION_STRATEGY values:\n")
    for (
        strategy,
        description,
    ) in InstanceTypeSelection.get_strategies_with_descriptions().items():
        print(f"{strategy.ljust(20)}: {description}")
    print()
    exit(0)


def list_instances_and_exit(args: ArgumentParser) -> None:
    regions: list[str] = []

    if not args.region:
        try:
            regions = cmdb.get_all_distinct_instance_regions()  # type: ignore
            if regions:
                regions.sort()
                logger.warning(
                    "WARN: No explicit --region input provided, scanning regions found from CMDB only: %s",
                    regions,
                )
        except Exception:
            logger.info("INFO: No regions found from CMDB")

    if args.region:
        regions = resolve_regions_from_fuzzy_input(args.region)
    elif not regions and not args.region:
        regions = resolve_regions_from_fuzzy_input(ALL_ENABLED_REGIONS)
        if regions:
            logger.warning(
                "WARN: No explicit --region input provided, scanning ALL enabled regions: %s",
                regions,
            )

    if not regions:
        logger.error("No regions provided")
        exit(1)

    errors = 0
    instances: list[dict] = []
    resumable_or_abandoned_volumes: list[dict] = []

    for reg in regions:
        logger.debug(
            "Fetching non-terminated pg-spot-operator instances for region '%s' ...",
            reg,
        )
        region_active_instance_names: set[str] = set()
        try:
            instance_descriptions = (
                get_all_active_operator_instances_from_region(reg)
            )
            if instance_descriptions:
                add_aws_tags_dict_from_list_tags(instance_descriptions)
                instances.extend(instance_descriptions)
                for t in instance_descriptions:
                    if t.get("TagsDict", {}).get(SPOT_OPERATOR_ID_TAG):
                        region_active_instance_names.add(
                            t["TagsDict"][SPOT_OPERATOR_ID_TAG]
                        )
        except Exception:
            logger.error("Failed to complete scan for region %s", reg)
            errors += 1

        logger.debug(
            "Checking for abandoned pg-spot-operator volumes in region '%s' ...",
            reg,
        )
        try:
            operator_vols = get_operator_volumes_in_region_full(reg)
            if operator_vols:
                for vol in operator_vols:
                    vol["Tags"] = {
                        tag["Key"]: tag["Value"] for tag in vol.get("Tags", [])
                    }
                    if (
                        vol["Tags"].get(SPOT_OPERATOR_ID_TAG)
                        and not vol["Tags"].get(SPOT_OPERATOR_ID_TAG)
                        in region_active_instance_names
                    ):
                        resumable_or_abandoned_volumes.append(vol)
        except Exception as e:
            logger.error(
                "Failed to describe volumes in region %s - might have abandoned volumes! Error: %s",
                reg,
                e,
            )
            errors += 1

    cols = [
        "Instance name",
        "AZ",
        "InstanceId",
        "InstanceType",
        "Market type",
        "vCPU",
        "$ (Mon.)",
        "VolumeId(s)",
        "Uptime",
        "PrivateIpAddress",
        "PublicIpAddress",
        "VpcId",
        "Expiration Date",
    ]
    tab = PrettyTable(cols)

    for i in instances:
        region = extract_region_from_az(
            i.get("Placement", {}).get("AvailabilityZone", "")
        )
        tab.add_row(
            [
                i.get("TagsDict", {}).get(SPOT_OPERATOR_ID_TAG),
                i.get("Placement", {}).get("AvailabilityZone"),
                i.get("InstanceId"),
                i.get("InstanceType"),
                "spot" if i.get("InstanceLifecycle") else "on-demand",
                i.get("CpuOptions", {}).get("CoreCount"),
                (
                    round(
                        get_current_hourly_spot_price_static(
                            region, i.get("InstanceType")
                        )
                        * 24
                        * 30,
                        1,
                    )
                    if i.get("InstanceLifecycle") == "spot"
                    else try_get_monthly_ondemand_price_for_sku(
                        region, i.get("InstanceType", "")
                    )
                ),
                (
                    ",".join(
                        [
                            x.get("Ebs", {}).get("VolumeId", "")
                            for x in i["BlockDeviceMappings"]
                            if x["DeviceName"]
                            != "/dev/xvda"  # Leave auto-the root vol
                        ]
                    )
                    if len(i.get("BlockDeviceMappings", [])) > 1
                    else None
                ),
                timestamp_to_human_readable_delta(
                    utc_datetime_to_local_time_zone(i.get("LaunchTime"))  # type: ignore
                ),
                i.get("PrivateIpAddress"),
                i.get("PublicIpAddress"),
                i.get("VpcId"),
                i.get("TagsDict", {}).get(SPOT_OPERATOR_EXPIRES_TAG),
            ]
        )

    print(tab)

    if resumable_or_abandoned_volumes:
        resumable_or_abandoned_volumes.sort(
            key=lambda x: x["AvailabilityZone"]
        )
        print("\nResumable / abandoned operator volumes:")
        cols_vols = [
            "Availability zone",
            "Instance name",
            "Volume create time",
            "Volume Id",
            "Size (GB)",
            "Volume type",
            "Throughput",
            "Iops",
        ]
        tab_vols = PrettyTable(cols_vols)
        for v in resumable_or_abandoned_volumes:
            tab_vols.add_row(
                [
                    v.get("AvailabilityZone"),
                    v.get("Tags", {}).get(SPOT_OPERATOR_ID_TAG),
                    humanize.naturaltime(utc_datetime_to_local_time_zone(v.get("CreateTime"))),  # type: ignore
                    v.get("VolumeId"),
                    v.get("Size"),
                    v.get("VolumeType"),
                    v.get("Throughput"),
                    v.get("Iops"),
                ]
            )
        print(tab_vols)

    exit(errors)


def list_instances_from_cmdb_and_exit() -> None:
    resumable_cols = [
        "Instance name",
        "Running",
        "Created on",
        "Region",
        "AZ",
        "Min. CPU",
        "Min. RAM",
        "Storage type",
        "Min. Storage",
        "Last provisioned",
        "Last VM",
        "Stopped on",
        "Resumable",
    ]
    tab = PrettyTable(resumable_cols)

    non_deleted_instances = cmdb.get_all_non_deleted_instances()
    non_deleted_instances.sort(key=lambda x: x.created_on)

    for nd_ins in non_deleted_instances:
        vm = cmdb.get_latest_vm_by_uuid(nd_ins.uuid, alive_only=False)
        if not vm:
            continue
        m = cmdb.get_last_successful_manifest_if_any(
            nd_ins.uuid, use_last_manifest=True
        )
        if not m:
            continue

        # Try to determine if VM online
        is_running = "False"
        try:
            running_instances_descs = (
                get_all_active_operator_instances_from_region(nd_ins.region)
            )
            for i in running_instances_descs:
                if i.get("InstanceId") == vm.provider_id:
                    is_running = "True"
                    break
        except Exception:
            logger.warning(
                "Failed to inquiry running state of VM %s in region %s",
                vm.provider_id,
                vm.region,
            )
            is_running = "?"

        tab.add_row(
            [
                nd_ins.instance_name,
                is_running,
                utc_datetime_to_local_time_zone(nd_ins.created_on),
                nd_ins.region,
                vm.availability_zone,
                nd_ins.cpu_min,
                nd_ins.ram_min,
                nd_ins.storage_type,
                nd_ins.storage_min,
                utc_datetime_to_local_time_zone(vm.created_on),
                vm.provider_id,
                nd_ins.stopped_on,
                not (
                    m.vm.storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL
                    and m.backup.type == BACKUP_TYPE_NONE
                ),
            ]
        )

    print(tab)

    exit()


def list_vm_create_events_and_exit(args: ArgumentParser) -> None:
    vm_create_cols = [
        "Created on",
        "Region",
        "AZ",
        "Instance name",
        "InstanceId",
        "InstanceType",
        "$ (Mon.)",
        "EC2 discount (%)",
    ]
    tab = PrettyTable(vm_create_cols)

    # Active instances - name / region filtering
    instances_to_list: list[str] = []
    for ins in cmdb.get_all_non_deleted_instances():
        if args.region and not re.findall(
            args.region, ins.region, re.IGNORECASE
        ):
            logger.debug(
                "Skipping ins %s in region %s due to --region=%s filter",
                ins.instance_name,
                ins.region,
                args.region,
            )
            continue
        if args.instance_name and not re.findall(
            args.instance_name, ins.instance_name, re.IGNORECASE
        ):
            logger.debug(
                "Skipping ins %s in region %s due to --instance-name=%s filter",
                ins.instance_name,
                ins.region,
                args.instance_name,
            )
            continue
        instances_to_list.append(ins.instance_name)

    # Fetch all historic VMs for (filtered) active instances
    vms: list[tuple[cmdb.Vm, cmdb.Instance]] = []

    for i in instances_to_list:
        vms.extend(cmdb.get_all_vms_by_instance_name(i))

    vms.sort(key=lambda x: (x[0]).created_on)

    for vm, ins in vms:

        tab.add_row(
            [
                utc_datetime_to_local_time_zone(vm.created_on),
                vm.region,
                vm.availability_zone,
                ins.instance_name,
                vm.provider_id,
                vm.sku,
                vm.price_spot,
                calc_discount_rate_str(vm.price_spot, vm.price_ondemand),
            ]
        )

    print(tab)

    exit(0)


def show_regional_spot_pricing_and_eviction_summary_and_exit(
    args: ArgumentParser,
) -> None:
    if is_explicit_aws_region_code(args.region):
        regions = [args.region]
    else:
        regions = region_regex_to_actual_region_codes(args.region)
        if not regions:
            logger.error(
                "Could not resolve region regex '%s' to any regions",
                args.region,
            )
            exit(1)
    logger.info(
        "Regions in consideration based on --region='%s' input: %s",
        args.region,
        regions,
    )
    reg_pricing: list[RegionalSpotPricingStats] = []
    for reg in regions:
        try:
            reg_pricing.append(get_spot_pricing_summary_for_region(reg))
        except Exception as e:
            logger.warning(str(e))
    reg_pricing.sort(key=lambda x: x.avg_spot_savings_rate, reverse=True)

    table: list[list] = [
        [
            "Region",
            "Avg. Spot EC2 Discount",
            "Expected Eviction Rate (Mo)",
            "Mean Time to Eviction (Mo)",
        ]
    ]
    tab = PrettyTable(table[0])
    max_reg_len = max(
        [len(x.region) for x in reg_pricing]
    )  # To justify nicely for multi-region
    for r in reg_pricing:
        tab.add_rows(
            [
                [
                    r.region.ljust(max_reg_len, " "),
                    str(-1 * r.avg_spot_savings_rate) + "%",
                    r.eviction_rate_group_label,
                    extract_mtf_months_from_eviction_rate_group_label(
                        r.eviction_rate_group_label
                    ),
                ]
            ]
        )

    print(tab)

    exit(0)


def any_action_flags_set(a: ArgumentParser) -> bool:
    return bool(
        a.instance_name
        or a.instance_types
        or a.instance_family
        or a.vm_only
        or a.vm_host
        or a.cpu_min
        or a.storage_min
        or a.teardown
        or a.teardown_region
        or a.list_regions
        or a.list_strategies
        or a.list_instances
        or a.list_instances_cmdb
        or a.list_avg_spot_savings
        or a.list_vm_creates
        or a.check_price
        or a.check_manifest
        or a.manifest
        or a.manifest_path
        or a.stop
        or a.resume
    )


def main():  # pragma: no cover

    global args
    args = validate_and_parse_args()

    logging.basicConfig(
        format=(
            "%(message)s"
            if (
                args.check_price
                or args.list_instances
                or args.list_instances_cmdb
                or args.list_vm_creates
            )
            else (
                "%(asctime)s %(levelname)s %(threadName)s %(filename)s:%(lineno)d %(message)s"
                if args.verbose
                else "%(asctime)s %(levelname)s %(message)s"
            )
        ),
        level=(logging.DEBUG if args.verbose else logging.INFO),
    )

    if not any_action_flags_set(args):
        args.print_help()
        exit(0)

    if args.list_regions:
        list_regions_and_exit()

    if args.list_avg_spot_savings:
        show_regional_spot_pricing_and_eviction_summary_and_exit(args)

    if args.list_strategies:
        list_strategies_and_exit()

    if args.check_manifest:
        check_manifest_and_exit(args)

    if not (args.manifest_path or args.manifest):
        check_cli_args_valid(args)

    if args.list_instances:
        init_cmdb_and_apply_schema_migrations_if_needed(args)
        list_instances_and_exit(args)

    if args.list_instances_cmdb:
        init_cmdb_and_apply_schema_migrations_if_needed(args)
        list_instances_from_cmdb_and_exit()

    if args.list_vm_creates:
        init_cmdb_and_apply_schema_migrations_if_needed(args)
        list_vm_create_events_and_exit(args)

    logger.debug("Args: %s", args.as_dict()) if args.debug else None

    if not (args.dry_run or running_in_check_or_list_mode(args)):
        ensure_single_instance_running(args.instance_name)

    if (
        not running_in_check_or_list_mode(args)
        and not args.dry_run
        and not args.vm_only
        and not (args.teardown_region or args.teardown)
        and not shutil.which("ansible-playbook")
    ):
        logger.warning(
            "ansible-playbook executable not found on the PATH - Postgres setup might not work!"
        )

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
        logger.info("Teardown complete for region %s", args.region)
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

    if args.stop:
        operator.stop_running_vms_if_any(
            args.instance_name or env_manifest.instance_name,
            args.dry_run,
        )
        exit(0)

    if not (
        args.dry_run
        or args.check_price
        or args.check_manifest
        or args.debug
        or args.list_regions
        or args.list_instances
        or args.list_vm_creates
    ):
        operator.operator_config_dir = args.config_dir
        clean_up_old_logs_if_any()

    # Download the Ansible scripts if missing and in some "real" mode, as not bundled to PyPI currently
    download_ansible_from_github_if_not_set_locally(args)

    logger.debug("Entering main loop")

    operator.do_main_loop(
        cli_env_manifest=env_manifest,
        cli_dry_run=args.dry_run,
        cli_debug=args.debug,
        cli_vault_password_file=args.vault_password_file,
        cli_user_manifest_path=args.manifest_path,
        cli_main_loop_interval_s=args.main_loop_interval_s,
        cli_destroy_file_base_path=args.destroy_file_base_path,
        cli_resume=args.resume,
        cli_teardown=args.teardown,
        cli_connstr_only=args.connstr_only,
        cli_connstr_format=args.connstr_format,
        cli_ansible_path=args.ansible_path,
        cli_connstr_output_path=args.connstr_output_path,
    )
