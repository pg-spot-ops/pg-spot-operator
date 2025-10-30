DEFAULT_API_VERSION: str = "v1"

CLOUD_AWS = "aws"
CLOUD_GCP = "gcp"
CLOUD_AZURE = "azure"
CLOUD_VAGRANT_LIBVIRT = "vagrant-libvirt"

DEFAULT_POSTGRES_MAJOR_VER = 18
MANIFEST_TYPE_INSTANCE: str = "pg_spot_operator_instance"

# Attached to all created cloud resources
SPOT_OPERATOR_ID_TAG = "pg-spot-operator-instance"
SPOT_OPERATOR_EXPIRES_TAG = "pg-spot-operator-expiration-date"

ACTION_ENSURE_VM = "ensure_vm"
ACTION_INSTANCE_SETUP = "single_instance_setup"
ACTION_MOUNT_DISKS = "mount_unattached_disks"
ACTION_DESTROY_INSTANCE = "destroy_instance"
ACTION_DESTROY_BACKUPS = "destroy_backups"
ACTION_TERMINATE_VM = "terminate_vm"

# So that can easily understand on the VM if and when setup was completed, plus can trigger a re-run by removing the marker
ACTION_COMPLETED_MARKER_FILE = "/root/pg_spot_operator_setup_completed_marker"

# "API" YAML sections constants
MF_SEC_VM_STORAGE_TYPE_LOCAL = "local"
MF_SEC_VM_STORAGE_TYPE_NETWORK = "network"

CPU_ARCH_X86 = "x86"
CPU_ARCH_ARM = "arm"

BACKUP_TYPE_PGBACKREST = "pgbackrest"
BACKUP_TYPE_NONE = "none"

DEFAULT_CONFIG_DIR = "~/.pg-spot-operator"

DEFAULT_INSTANCE_SELECTION_STRATEGY = "balanced"

ALL_ENABLED_REGIONS = "all-enabled-regions"

DEFAULT_SSH_PUBKEY_PATH = "~/.ssh/id_rsa.pub"

CONNSTR_FORMAT_AUTO = (
    "auto"  # auto = "postgres" if admin user / password set, otherwise "ssh"
)
CONNSTR_FORMAT_SSH = "ssh"
CONNSTR_FORMAT_ANSIBLE = "ansible"
CONNSTR_FORMAT_POSTGRES = "postgres"

DEFAULT_VM_LOGIN_USER = "pgspotops"

# https://aws.amazon.com/ebs/pricing/
APPROX_EBS_PRICE_PER_GB = 0.08  # For most regions as of 2025 Oct
