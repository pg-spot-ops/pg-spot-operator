# Environment / CLI options

## General

* **--list-instances / LIST_INSTANCES** List all running operator managed VMs in specified region(s) and exit
* **--list-instances-cmdb / LIST_INSTANCES_CMDB** # List non-deleted instances from CMDB for all regions
* **--list-regions / LIST_REGIONS** List AWS datacenter locations and exit
* **--list-strategies / LIST_STRATEGIES** Display available instance selection strategies and exit
* **--list-avg-spot-savings / LIST_AVG_SPOT_SAVINGS** Display avg. regional Spot savings and eviction rates to choose the best region. Can apply the --region filter.
* **--list-vm-creates / LIST_VM_CREATES** Show VM provisioning times for active instances. Region / instance name filtering applies.
* **--check-price / CHECK_PRICE** Just resolve the HW reqs, show Spot price / discount rate and exit. No AWS creds required.
* **--check-manifest / CHECK_PRICE** Validate CLI input or instance manifest file and exit
* **--dry-run / DRY_RUN** Perform a dry-run VM create + create the Ansible skeleton. For example to check if cloud credentials allow Spot VM creation.
* **--debug / DEBUG** Don't clean up Ansible run files plus extra developer outputs.
* **--vm-only / VM_ONLY** Skip Ansible / Postgres setup
* **--no-mount-disks / NO_MOUNT_DISKS** Skip data disks mounting via Ansible. Relevant only is --vm-only set.
* **--persistent-vms / PERSISTENT_VMS** Run on normal / on-demand VMs instead of Spot. Default: false
* **--config-dir / CONFIG_DIR** (Default: ~/.pg-spot-operator) Where the engine keeps its internal state / configuration
* **--main-loop-interval-s / MAIN_LOOP_INTERVAL_S** (Default: 60)  Main loop sleep time. Reduce a bit to detect failures earlier / improve uptime
* **--verbose / VERBOSE** More chat

## Instance

* **--instance-name / INSTANCE_NAME** Required if not using a YAML manifest
* **--region / REGION** Required for modes that actually do something, as we don't assume a persistent config store. Optional if --zone set.
  *PS* Note that it can also be a regex in `--check-price` mode, to select the cheapest region of a continent, e.g. 'eu-'
* **--zone / ZONE** To fix the placement within the region. Not recommended, as prices differ considerably within regions' zones.
* **--postgres-version / POSTGRES_VERSION** (Default: 17)
* **--manifest-path / MANIFEST_PATH** Full user manifest YAML path if not using the CLI / single params
* **--manifest / MANIFEST** Full manifest input as YAML text
* **--stop / STOP** Stop the VM but leave disks around for a later resume / teardown
* **--resume / RESUME** Resurrect the input --instance-name using last known settings
* **--teardown / TEARDOWN** Delete VM and any other created resources for the give instance
* **--teardown-region / TEARDOWN_REGION** Delete all operator tagged resources in the whole region. Not safe if there are multiple Spot Operator users under the account!
* **--expiration-date / EXPIRATION_DATE** ISO 8601 datetime. E.g.: "2025-02-01 00:00+02"
* **--self-termination / SELF_TERMINATION** On --expiration-date. Assumes --self-termination-access-key-id / --self-termination-secret-access-key set.
* **--user-tags / USER_TAGS** Any custom tags / labels to attach to the VM. E.g. team=backend

## Integration

* **--connstr-only / CONNSTR_ONLY** Ensure VM + Postgres, output the connstr to stdout and exit. Pipe-friendly
* **--connstr-format / CONNSTR_FORMAT** \[auto* | ssh | ansible | postgres\]. auto = "postgres" if admin user / password set, otherwise "ssh"
* **--setup-finished-callback / SETUP_FINISHED_CALLBACK** An optional executable to propagate the connect string / VM IPs somewhere.
  See README_integration.md for input parameters description fed into the script by the engine.  
* **--connstr-output-path / CONNSTR_OUTPUT_PATH** When set write Postgres (or SSH if --vm-only) connect string into a file
* **--connstr-bucket / CONNSTR_BUCKET** (Required for S3 push to work)
* **--connstr-bucket-key / CONNSTR_BUCKET_KEY** (Required for S3 push to work)
* **--connstr-bucket-region / CONNSTR_BUCKET_REGION** Don't have to be set if region matched with the instance
* **--connstr-bucket-endpoint / CONNSTR_BUCKET_ENDPOINT** Don't have to be set if region matched with the instance
* **--connstr-bucket-access-key / CONNSTR_BUCKET_ACCESS_KEY** If not set main AWS creds used
* **--connstr-bucket-access-secret / CONNSTR_BUCKET_ACCESS_SECRET** If not set main AWS creds used

## Hardware selection

* **--storage-min / STORAGE_MIN** # In GB. Precise provisioning size for network volumes, minimum for --storage-type=local. -1 is a special value for --storage-type=network not to create a data volume.
* **--storage-type / STORAGE_TYPE** (Default: network) Allowed values: \[ network | local \].
* **--storage-speed-class / STORAGE_SPEED_CLASS** (Default: ssd) Allowed values: \[ hdd | ssd | nvme \].
* **--volume-type / VOLUME_TYPE** Allowed values: \[ gp2, gp3\*, io1, io2, st1, sc1 \]
* **--volume-iops / VOLUME_IOPS** Set IOPS explicitly. Max. gp2/gp3=16K, io1=64K, io2=256K, gp3 def=3K
* **--volume-throughput / VOLUME_THROUGHPUT** Set gp3 volume throughput explicitly in MiB/s. Max 1000. Default 125.
* **--os-disk-size / OS_DISK_SIZE** OS disk size in GB. Default 20.
* **--cpu-min / CPU_MIN** Minimal CPUs to consider an instance type suitable
* **--cpu-max / CPU_MAX** Maximum CPUs to consider an instance type suitable. Required for the random selection strategy to cap the costs. 
* **--allow-burstable / ALLOW_BURSTABLE** Allow t-class instance types
* **--ram-min / RAM_MIN** Minimal RAM (in GB) to consider an instance type suitable. Default: 1
* **--ram-max / RAM_MAX** Maximum RAM (in GB) to consider an instance type suitable. To limit cost for eviction-rate strategy.
* **--selection-strategy / SELECTION_STRATEGY** (Default: balanced) Allowed values: \[ balanced | cheapest | eviction-rate | random \]. Random can work better when getting a lot of evictions. 
* **--instance-types / INSTANCE_TYPES** To explicitly control the instance type selection. E.g. "i3.xlarge,i3.2xlarge"
* **--instance-family / INSTANCE_FAMILY** Regex. e.g. 'r(6|7)'
* **--cpu-arch / CPU_ARCH** arm / intel / amd / x86
* **--max-price / MAX_PRICE** Maximum hourly price cap to select / launch VMs
* **--stripes / STRIPES** 1-28 stripe volumes allowed. Default 1 i.e. no striping
* **--stripe-size-kb / STRIPE_SIZE_KB** 4-4096 KB range. Default 64

# Postgres

* **--admin-user / ADMIN_USER** If set, a Postgres user for external access is created.
* **--admin-password / ADMIN_PASSWORD** Required when --admin-user set. Better make it a strong one for public instances.
* **--admin-is-superuser / ADMIN_IS_SUPERUSER** (Default: false) If set, the --admin-user will be a real unrestricted Postgres superuser (with OS access)
* **--tuning-profile / TUNING_PROFILE** Default: "default". Allowed values: \[ none | default | oltp | analytics | web | throwaway\].
* **--app-db-name / APP_DB_NAME** If set, an extra DB named --app-db-name will be created 
* **--os-extra-packages / OS_EXTRA_PACKAGES** Any `apt` available packages the user sees necessary. Needed for some extensions. E.g. "postgresql-16-postgis-3,postgresql-16-pgrouting"
* **--shared-preload-libraries / SHARED_PRELOAD_LIBRARIES** (Default: pg_stat_statements). Comma separated
* **--extensions / EXTENSIONS** (Default: pg_stat_statements). Comma separated

# Security / Access

* **--aws-access-key-id / AWS_ACCESS_KEY_ID** AWS creds. If not set the default profile is used.  
* **--aws-secret-access-key / AWS_SECRET_ACCESS_KEY** AWS creds. If not set the default profile is used.
* **--self-termination-access-key-id / SELF_TERMINATION_ACCESS_KEY_ID** AWS creds to be placed on the VM if --self-termination set
* **--self-termination-secret-access-key / SELF_TERMINATION_SECRET_ACCESS_KEY** AWS creds to be placed on the VM if --self-termination set
* **--private-ip-only / PRIVATE_IP_ONLY** (Default: false) If "true" then only VPC / private subnet accessible.
* **--static-ip-addresses / STATIC_IP_ADDRESSES** (Default: false) Set to disable the default "IP floating" behaviour. If "true" and in Public IP mode then a fixed Elastic IP is assigned. Has extra cost, plus limited availability on account level usually.
* **--vault-password-file / VAULT_PASSWORD_FILE** Needed if using Ansible Vault encrypted strings in the manifest
* **--aws-security-group-ids / AWS_SECURITY_GROUP_IDS** SG rules (a firewall essentially) are "merged" if multiple provided
* **--aws-vpc-id / AWS_VPC_ID** If not set default VPC of --region used
* **--aws-subnet-id / AWS_SUBNET_ID** To place the created VMs into a specific network
* **--ssh-keys / SSH_KEYS** Comma separated SSH pubkeys to add to the backing VM
* **--ssh-private-key / SSH_PRIVATE_KEY** (Default: ~/.ssh/id_rsa) To use a non-default SSH key to access the VM
* **--aws-key-pair-name / AWS_KEY_PAIR_NAME** To grant an existing AWS SSH key pair SSH access the VM. Must have the private key for actual access
* **--pg-hba-lines / PG_HBA_LINES** Valid pg_hba.conf lines to override operator world-access defaults. Comma separated

# Backup

* **--backup-s3-bucket / BACKUP_S3_BUCKET** If set, pgBackRest will be configured
* **--backup-retention-days / BACKUP_RETENTION_DAYS** (Default: 1)
* **--backup-cipher / BACKUP_CIPHER** pgBackRest cipher password. If set backups will be encrypted.
* **--backup-s3-key / BACKUP_S3_KEY** pgBackRest S3 access
* **--backup-s3-key-secret / BACKUP_S3_KEY_SECRET** pgBackRest S3 access

# Monitoring

* **--monitoring / MONITORING** (Default: false) To enable extra hardware monitoring via *node_exporter* on the VM
* **--grafana-externally-accessible / GRAFANA_EXTERNALLY_ACCESSIBLE** (Default: true) If to listen on all interfaces on port 3000. Relevant only if --monitoring set.
* **--grafana-anonymous / GRAFANA_ANONYMOUS** (Default: true). If "false" need a password to view the metrics. Login info: pgspotops / --instance-name

# Develepment / testing

* **--vm-host / VM_HOST** Skip the VM creation step and use the provided hostname / IP. Useful for dev-testing.
* **--vm-login-user/ VM_LOGIN_USER** Ansible SSH login user. Defaults to "pgspotops"
* **--ansible-path / ANSIBLE_PATH** Use a non-default Ansible path. In case want to customize something etc.
* **--destroy-file-base-path / DESTROY_FILE_BASE_PATH** (Default: /tmp/destroy-) If a file named base+instance detected, the instance is expired and the program exits
