DEFAULT_API_VERSION: str = "v1"

CLOUD_AWS = "aws"
CLOUD_GCP = "gcp"
CLOUD_AZURE = "azure"
CLOUD_VAGRANT_LIBVIRT = "vagrant-libvirt"

DEFAULT_POSTGRES_MAJOR_VER = 16
MANIFEST_TYPE_INSTANCE: str = "pg_spot_operator_instance"

# Attached to all created cloud resources
SPOT_OPERATOR_ID_TAG = "pg-spot-operator-instance"
SPOT_OPERATOR_EXPIRES_TAG = "pg-spot-operator-expiration-date"

ACTION_ENSURE_VM = "ensure_vm"
ACTION_INSTANCE_SETUP = "single_instance_setup"
ACTION_DESTROY_INSTANCE = "destroy_instance"
ACTION_DESTROY_BACKUPS = "destroy_backups"
ACTION_TERMINATE_VM = "terminate_vm"

# "API" YAML sections constants
MF_SEC_VM_STORAGE_TYPE_LOCAL = "local"
MF_SEC_VM_STORAGE_TYPE_NETWORK = "network"

CPU_ARCH_X86 = "x86"
CPU_ARCH_ARM = "arm"

BACKUP_TYPE_PGBACKREST = "pgbackrest"
