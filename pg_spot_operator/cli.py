import logging
import os.path

from tap import Tap

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
    user_manifest_path: str = os.getenv(
        "PGSO_USER_MANIFEST_PATH", ""
    )  # User manifest path
    ansible_path: str = os.getenv("PGSO_ANSIBLE_PATH", "./ansible")
    main_loop_interval_s: int = int(
        os.getenv("PGSO_MAIN_LOOP_INTERVAL_S")
        or 60  # Increase if causing too many calls to the cloud API
    )
    config_dir: str = os.getenv(
        "PGSO_CONFIG_DIR", "~/.pg-spot-operator"
    )  # For internal state keeping
    sqlite_path: str = os.getenv(
        "PGSO_SQLITE_PATH", "~/.pg-spot-operator/pgso.db"
    )
    default_vault_password_file: str = os.getenv(
        "PGSO_DEFAULT_VAULT_PASSWORD_FILE", ""
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
    instance_name: str = os.getenv("PGSO_INSTANCE_NAME", "")  # Mandatory
    instance_type: str = os.getenv("PGSO_INSTANCE_TYPE", "")
    cloud: str = os.getenv("PGSO_CLOUD", "aws")
    region: str = os.getenv("PGSO_REGION", "")  # Mandatory
    zone: str = os.getenv("PGSO_ZONE", "")
    cpu_min: int = int(os.getenv("PGSO_CPU_MIN", "0"))
    ram_min: int = int(os.getenv("PGSO_RAM_MIN", "0"))
    storage_min: int = int(os.getenv("PGSO_STORAGE_MIN", "100"))
    storage_type: str = os.getenv("PGSO_STORAGE_TYPE", "network")
    storage_speed_class: str = os.getenv("PGSO_STORAGE_SPEED_CLASS", "ssd")
    expires_on: str = os.getenv(
        "PGSO_EXPIRES_ON", ""
    )  # Instance expiry / teardwon timestamp
    public_ip: bool = to_bool(os.getenv("PGSO_PUBLIC_IP", "true"))


args: ArgumentParser | None = None


def validate_and_parse_args() -> ArgumentParser:
    args = ArgumentParser(
        prog="pg-spot-operator",
        description="Maintains Postgres on Spot VMs",
        underscores_to_dashes=True,
    ).parse_args()

    return args


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

    logger.debug("Args: %s", args.as_dict()) if args.verbose else None


def do_check_manifests_and_exit(args):
    pass
