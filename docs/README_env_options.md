# Environment / CLI options

## General

* **--list-instances / PGSO_LIST_INSTANCES** List all running operator managed VMs in specified region(s) and exit
* **--list-regions / PGSO_LIST_REGIONS** List AWS datacenter locations and exit
* **--list-strategies / PGSO_LIST_STRATEGIES** Display available instance selection strategies and exit
* **--check-price / PGSO_CHECK_PRICE** Just resolve the HW reqs, show Spot price / discount rate and exit. No AWS creds required.
* **--check-manifest / PGSO_CHECK_PRICE** Validate CLI input or instance manifest file and exit
* **--dry-run / PGSO_DRY_RUN** Perform a dry-run VM create + create the Ansible skeleton. For example to check if cloud credentials allow Spot VM creation.
* **--vm-only / PGSO_VM_ONLY** Skip Ansible / Postgres setup
* **--config-dir / PGSO_CONFIG_DIR** (Default: ~/.pg-spot-operator) Where the engine keeps its internal state / configuration
* **--main-loop-interval-s / PGSO_MAIN_LOOP_INTERVAL_S** (Default: 60)  Main loop sleep time. Reduce a bit to detect failures earlier / improve uptime
* **--verbose / PGSO_VERBOSE** More chat

## Instance

* **--instance-name / PGSO_INSTANCE_NAME** Required if not using a YAML manifest
* **--region / PGSO_REGION** Required for modes that actually do something, as we don't assume a persistent config store. Optional if --zone set.
  *PS* Note that it can also be a regex in `--check-price` mode, to select the cheapest region of a continent, e.g. 'eu-'
* **--zone / PGSO_ZONE** To fix the placement within the region. Not recommended, as prices differ considerably within regions' zones.
* **--postgres-version / PGSO_POSTGRES_VERSION** (Default: 16)
* **--manifest-path / PGSO_MANIFEST_PATH** Full user manifest YAML path if not using the CLI / single params
* **--manifest / PGSO_MANIFEST** Full manifest input as YAML text
* **--teardown / PGSO_TEARDOWN** Delete VM and any other created resources for the give instance
* **--teardown-region / PGSO_TEARDOWN_REGION** Delete all operator tagged resources in the whole region. Not safe if there are multiple Spot Operator users under the account!
* **--expiration-date / PGSO_EXPIRATION_DATE** ISO 8601 datetime.
* **--self-termination / PGSO_SELF_TERMINATION** On --expiration-date. Assumes --self-termination-access-key-id / --self-termination-secret-access-key set.
* **--user-tags / PGSO_USER_TAGS** Any custom tags / labels to attach to the VM. E.g. team=backend

## Integration

* **--connstr-output-only / PGSO_CONNSTR_OUTPUT_ONLY** Ensure VM + Postgres, output the connstr to stdout and exit. Pipe-friendly
* **--connstr-format / PGSO_CONNSTR_FORMAT** ssh | ansible. Relevant when --connstr-output-only + --vm-only set
* **--setup-finished-callback / PGSO_SETUP_FINISHED_CALLBACK** An optional executable to propagate the connect string somewhere
* **--setup-finished-callback / PGSO_SETUP_FINISHED_CALLBACK** An optional executable to propagate the connect string somewhere
* **--connstr-bucket / CONNSTR_BUCKET** (Required for S3 push to work)
* **--connstr-bucket-key / CONNSTR_BUCKET_KEY** (Required for S3 push to work)
* **--connstr-bucket-region / CONNSTR_BUCKET_REGION** Don't have to be set if region matched with the instance
* **--connstr-bucket-endpoint / CONNSTR_BUCKET_ENDPOINT** Don't have to be set if region matched with the instance
* **--connstr-bucket-access-key / CONNSTR_BUCKET_ACCESS_KEY** If not set main AWS creds used
* **--connstr-bucket-access-secret / CONNSTR_BUCKET_ACCESS_SECRET** If not set main AWS creds used

## Hardware selection

* **--storage-min / PGSO_STORAGE_MIN** Minimal disk size (in GB) to allocate. For local storage instances the actual size might be bigger.
* **--storage-type / PGSO_STORAGE_TYPE** (Default: network) Allowed values: \[ network | local \].
* **--storage-speed-class / PGSO_STORAGE_SPEED_CLASS** (Default: ssd) Allowed values: \[ hdd | ssd | nvme \].
* **--volume-type / VOLUME_TYPE** Allowed values: \[ gp2, gp3\*, io1, io2 \]
* **--volume-iops / VOLUME_IOPS** Set IOPS explicitly. Max. gp2/gp3=16K, io1=64K, io2=256K, gp3 def=3K
* **--volume-throughput / VOLUME_THROUGHPUT** Set gp3 volume throughput explicitly in MiB/s. Max 1000. Default 125.
* **--cpu-min / PGSO_CPU_MIN** Minimal CPUs to consider an instance type suitable
* **--cpu-max / PGSO_CPU_MAX** Maximum CPUs to consider an instance type suitable. Required for the random selection strategy to cap the costs. 
* **--ram-min / PGSO_RAM_MIN** Minimal RAM (in GB) to consider an instance type suitable
* **--selection-strategy / PGSO_SELECTION_STRATEGY** (Default: balanced) Allowed values: \[ balanced | cheapest | eviction-rate | random \]. Random can work better when getting a lot of evictions. 
* **--instance-types / PGSO_INSTANCE_TYPES** To explicitly control the instance type selection. E.g. "i3.xlarge,i3.2xlarge"
* **--instance-family / PGSO_INSTANCE_FAMILY** Regex. e.g. 'r(6|7)'
* **--cpu-arch / PGSO_CPU_ARCH** arm / intel / amd / x86

# Postgres

* **--admin-user / PGSO_ADMIN_USER** If set, a Postgres user for external access is created.
* **--admin-password / PGSO_ADMIN_PASSWORD** Required when --admin-user set. Better make it a strong one for public instances.
* **--admin-is-superuser / PGSO_ADMIN_IS_SUPERUSER** (Default: false) If set, the --admin-user will be a real unrestricted Postgres superuser (with OS access)
* **--tuning-profile / PGSO_TUNING_PROFILE** Default: "default". Allowed values: \[ none | default | oltp | analytics | web \].
* **--app-db-name / PGSO_APP_DB_NAME** If set, an extra DB named --app-db-name will be created 
* **--os-extra-packages / PGSO_OS_EXTRA_PACKAGES** Any `apt` available packages the user sees necessary. Needed for some extensions. E.g. "postgresql-16-postgis-3,postgresql-16-pgrouting"
* **--shared-preload-libraries / PGSO_SHARED_PRELOAD_LIBRARIES** (Default: pg_stat_statements). Comma separated
* **--extensions / PGSO_EXTENSIONS** (Default: pg_stat_statements). Comma separated

# Security / Access

* **--aws-access-key-id / PGSO_AWS_ACCESS_KEY_ID** AWS creds. If not set the default profile is used.  
* **--aws-secret-access-key / PGSO_AWS_SECRET_ACCESS_KEY** AWS creds. If not set the default profile is used.
* **--self-termination-access-key-id / PGSO_SELF_TERMINATION_ACCESS_KEY_ID** AWS creds to be placed on the VM if --self-termination set
* **--self-termination-secret-access-key / PGSO_SELF_TERMINATION_SECRET_ACCESS_KEY** AWS creds to be placed on the VM if --self-termination set
* **--assign-public-ip / PGSO_ASSIGN_PUBLIC_IP** (Default: true) If "false" then only VPC accessible.
* **--vault-password-file / PGSO_VAULT_PASSWORD_FILE** Needed if using Ansible Vault encrypted strings in the manifest
* **--aws-security-group-ids / PGSO_AWS_SECURITY_GROUP_IDS** SG rules (a firewall essentially) are "merged" if multiple provided
* **--aws-vpc-id / PGSO_AWS_VPC_ID** If not set default VPC of --region used
* **--aws-subnet-id / PGSO_AWS_SUBNET_ID** To place the created VMs into a specific network
* **--ssh-keys / PGSO_SSH_KEYS** Comma separated SSH pubkeys to add to the backing VM
* **--ssh-private-key / PGSO_SSH_PRIVATE_KEY** (Default: ~/.ssh/id_rsa) To use a non-default SSH key to access the VM
* **--aws-key-pair-name / PGSO_AWS_KEY_PAIR_NAME** To grant an existing AWS SSH key pair SSH access the VM. Must have the private key for actual access
* **--pg-hba-lines / PGSO_PG_HBA_LINES** Valid pg_hba.conf lines to override operator world-access defaults. Comma separated

# Backup

* **--backup-s3-bucket / PGSO_BACKUP_S3_BUCKET** If set, pgBackRest will be configured
* **--backup-retention-days / PGSO_BACKUP_RETENTION_DAYS** (Default: 1)
* **--backup-cipher / PGSO_BACKUP_CIPHER** pgBackRest cipher password. If set backups will be encrypted.
* **--backup-s3-key / PGSO_BACKUP_S3_KEY** pgBackRest S3 access
* **--backup-s3-key-secret / PGSO_BACKUP_S3_KEY_SECRET** pgBackRest S3 access

# Monitoring

* **--monitoring / PGSO_MONITORING** (Default: false) To enable extra hardware monitoring via *node_exporter* on the VM
* **--grafana-externally-accessible / PGSO_GRAFANA_EXTERNALLY_ACCESSIBLE** (Default: true) If to listen on all interfaces on port 3000. Relevant only if --monitoring set.
* **--grafana-anonymous / PGSO_GRAFANA_ANONYMOUS** (Default: true). If "false" need a password to view the metrics. Login info: pgspotops / --instance-name

# Develepment / testing

* **--vm-host / PGSO_VM_HOST** Skip the VM creation step and use the provided hostname / IP. Useful for dev-testing.
* **--vm-login-user/ PGSO_LOGIN_USER** User given user for Ansible SSH login. Useful for dev-testing.
* **--ansible-path / PGSO_ANSIBLE_PATH** Use a non-default Ansible path. In case want to customize something etc.
* **--destroy-file-base-path / PGSO_DESTROY_FILE_BASE_PATH** (Default: /tmp/destroy-) If a file named base+instance detected, the instance is expired and the program exits
