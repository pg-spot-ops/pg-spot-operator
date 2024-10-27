# Environment / CLI options

## General

--check-price / PGSO_CHECK_PRICE
: Just resolve the HW reqs, show Spot price / discount rate and exit

--check-manifest / PGSO_CHECK_PRICE
: Validate CLI input / instance manifest and exit

--dry-run / PGSO_DRY_RUN
: Perform a dry-run VM create + create the Ansible skeleton. For example to check if cloud credentials allow Spot VM creation.

--vm-only / PGSO_VM_ONLY
: Skip Ansible / Postgres setup

--config-dir / PGSO_CONFIG_DIR
: Where the engine keeps its internal state / configuration. (Default: ~/.pg-spot-operator)

--main-loop-interval-s / PGSO_MAIN_LOOP_INTERVAL_S
: Main loop sleep time. Reduce a bit to detect failures earlier / improve uptime. (Default: 60)

--verbose / PGSO_VERBOSE
: More chat

## Instance

--instance-name / PGSO_INSTANCE_NAME
: Required if not using a YAML manifest

--region / PGSO_REGION
: Required for modes that actually do something. As we don't assume a persistent config store. Optional if --zone set.

--zone / PGSO_ZONE
: To fix the placement within the region. Not recommended, as prices differ considerably within regions' zones.

--postgresql-version / PGSO_POSTGRESQL_VERSION
: The major Postgres version. (Default: 16)

--manifest-path / PGSO_MANIFEST_PATH
: Full user manifest YAML path if not using the CLI / single params

--manifest / PGSO_MANIFEST
: Full manifest input as YAML text

--teardown / PGSO_TEARDOWN
: Delete VM and any other created resources for the give instance

--teardown-region / PGSO_TEARDOWN_REGION
: Delete all operator tagged resources in the whole region. Not safe if there are multiple Spot Operator users under the account!

--expiration-date / PGSO_EXPIRATION_DATE
: ISO 8601 datetime.

--self-terminate / PGSO_SELF_TERMINATE
: On --expiration-date. Assumes --self-terminate-access-key-id / --self-terminate-secret-access-key set. 

--user-tags / PGSO_USER_TAGS
: Any custom tags / labels to attach to the VM. E.g. team=backend

## Integration

--connstr-output-only / PGSO_CONNSTR_OUTPUT_ONLY
: Ensure VM + Postgres, output the connstr to stdout and exit. Pipe-friendly

--setup-finished-callback / PGSO_SETUP_FINISHED_CALLBACK
: An optional executable to propagate the connect string somewhere

## Hardware selection

--storage-min / PGSO_STORAGE_MIN
: Minimal disk size (in GB) to allocate. For local storage instances the actual size might be bigger.

--storage-type / PGSO_STORAGE_TYPE
: Allowed values: \[ network | local \]. (Default: network)

--cpu-min / PGSO_CPU_MIN
: Minimal CPUs to consider an instance type suitable

--cpu-max / PGSO_CPU_MAX
: Maximum CPUs to consider an instance type suitable. Required for the random selection strategy to cap the costs. 

--ram-min / PGSO_RAM_MIN
: Minimal RAM (in GB) to consider an instance type suitable

--selection-strategy / PGSO_SELECTION_STRATEGY
: Allowed values: \[ cheapest | random \]. Random can work better when getting a lot of evictions. (Default: cheapest)  

--instance-types / PGSO_INSTANCE_TYPES
: To explicitly control the instance type selection. E.g. "i3.xlarge,i3.2xlarge"

--cpu-architecture / PGSO_CPU_ARCHITECTURE
: arm / intel / amd / x86

# Postgres

--admin-user / PGSO_ADMIN_USER
: If set, a Postgres user for external access is created.

--admin-user-password / PGSO_ADMIN_USER_PASSWORD
: Required when --admin-user set. Better make it a strong one for public instances.

--admin-is-superuser / PGSO_ADMIN_IS_SUPERUSER
: If set, the --admin-user will be a real unrestricted Postgres superuser (with OS access). (Default: false)

--tuning-profile / PGSO_TUNING_PROFILE
: To auto-tune the Postgres instance if approximate use case is know. Allowed values: \[ none | default | oltp | analytics | web \]. Default: "default"

--app-db-name / PGSO_APP_DB_NAME
: If set, an extra DB named --app-db-name will be created 

--os-extra-packages / PGSO_OS_EXTRA_PACKAGES
: Any `apt` available (from Debian 12 + PGDG repos) packages the user sees necessary. Needed for some extensions. E.g. "postgresql-16-postgis-3,postgresql-16-pgrouting"

--shared-preload-libraries / PGSO_SHARED_PRELOAD_LIBRARIES
: To explicitly set the `shared_preload_libraries`. Comma separated. (Default: pg_stat_statements)

--extensions / PGSO_EXTENSIONS
: Extensions to be pre-created (CREATE EXTENSION) during Ansible setup. Comma separated. (Default: pg_stat_statements)

# Security / Access

--aws-access-key-id / PGSO_AWS_ACCESS_KEY_ID
: AWS creds. If not set the default profile is used.  

--aws-secret-access-key / PGSO_AWS_SECRET_ACCESS_KEY
: AWS creds. If not set the default profile is used.

--self-terminate-access-key-id / PGSO_SELF_TERMINATE_ACCESS_KEY_ID
: AWS creds to be placed on the VM if --self-terminate set

--self-terminate-secret-access-key / PGSO_SELF_TERMINATE_SECRET_ACCESS_KEY
: AWS creds to be placed on the VM if --self-terminate set

--assign-public-ip / PGSO_ASSIGN_PUBLIC_IP
: If "false" then only VPC accessible. (Default: true)

--vault-password-file / PGSO_VAULT_PASSWORD_FILE
: Needed if using Ansible Vault encrypted strings in the manifest

--aws-security-group-ids / PGSO_AWS_SECURITY_GROUP_IDS
: Security Group (a firewall essentially) rules are "merged" if multiple provided

--aws-vpc-id / PGSO_AWS_VPC_ID
: If not set default VPC of --region used

--aws-subnet-id / PGSO_AWS_SUBNET_ID
: To place the created VMs into a specific network

--ssh-keys / PGSO_SSH_KEYS
: Comma separated SSH pubkeys to add to the backing VM

--ssh-private-key / PGSO_SSH_PRIVATE_KEY
: (Default: ~/.ssh/id_rsa) To use a non-default SSH key to access the VM

# Backup

--backup-s3-bucket / PGSO_BACKUP_S3_BUCKET
: If set, pgBackRest S3 backups will be configured. A must for data persistence if using --storage-type=local.  

--backup-retention-days / PGSO_BACKUP_RETENTION_DAYS
: Fed into pgBackRest. The actual retention time will be a bit longer though in practice (Default: 1)

--backup-cipher / PGSO_BACKUP_CIPHER
: pgBackRest cipher password. If set backups will be encrypted.

--backup-s3-key / PGSO_BACKUP_S3_KEY
: pgBackRest S3 access

--backup-s3-key-secret / PGSO_BACKUP_S3_KEY_SECRET
: pgBackRest S3 access

# Monitoring

--monitoring / PGSO_MONITORING
: To enable extra hardware monitoring via *node_exporter* on the VM. (Default: false)

--grafana-externally-accessible / PGSO_GRAFANA_EXTERNALLY_ACCESSIBLE
: If to listen on all interfaces on port 3000. Relevant only if --monitoring set. (Default: true)

--grafana-anonymous / PGSO_GRAFANA_ANONYMOUS
: If "false" need a password to view the metrics. Login info: pgspotops / --instance-name. (Default: true)

# Develepment / testing

--vm-host / PGSO_VM_HOST
: Skip the VM creation step and use the provided hostname / IP. Useful for dev-testing.

--vm-login-user/ PGSO_LOGIN_USER
: User given user for Ansible SSH login. Useful for dev-testing.

--ansible-path / PGSO_ANSIBLE_PATH
: Use a non-default Ansible path. In case want to customize something etc.

--destroy-file-base-path / PGSO_DESTROY_FILE_BASE_PATH
: If a file named base+instance detected, the instance is expired and the program exits. (Default: /tmp/destroy-)
