import functools
import json
import logging
import os
import subprocess
import urllib.request
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def run_process_with_output(
    runnable_path: str, input_params: list[str]
) -> tuple[int, str]:
    p = subprocess.Popen(
        [runnable_path] + input_params,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    stdout, _ = p.communicate()

    return p.returncode, stdout


def pg_config_lines_to_dict(extra_config_lines: list[str]) -> dict:
    ret = {}
    for line in extra_config_lines:
        splits = line.split("=")
        ret[splits[0].strip()] = line
    return ret


def merge_user_and_tuned_non_conflicting_config_params(
    config_lines_tuned: list[str], config_lines_user: list[str]
) -> list[str]:
    """User input wins over tuned config lines
    Input lines are ready-to-use PG conf lines a la: work_mem='64MB'
    """
    if not config_lines_user:
        return config_lines_tuned

    merged = config_lines_user.copy()

    user_set_params = pg_config_lines_to_dict(config_lines_user)

    for tuned_line in config_lines_tuned:
        splits = tuned_line.split("=")
        if splits[0].strip() in user_set_params:
            continue
        merged.append(tuned_line)
    return merged


def merge_action_output_params(
    collected_output_params: dict | None,
    engine_prepopulated_output_vars: dict | None,
) -> dict:
    output_params_merged = {}
    if (
        engine_prepopulated_output_vars
    ):  # Engine can pre-populate outputs like resolved CPU count etc
        output_params_merged.update(engine_prepopulated_output_vars)
    if (
        collected_output_params
    ):  # Action handler generated output overrides any presets
        output_params_merged.update(collected_output_params)
    return output_params_merged


def get_default_azure_subscription_id_from_local_profile() -> str | None:
    """Assumes AZ CLI login done"""
    local_az_profile_file = os.path.expanduser("~/.azure/azureProfile.json")

    profiles = {}
    try:
        profiles = json.loads(
            open(local_az_profile_file).read().replace("\uFEFF", "")
        )
    except Exception:
        pass
    if not profiles:
        return None
    default_profile = [
        p for p in profiles.get("subscriptions", []) if p.get("isDefault")
    ]
    return default_profile[0].get("id")


def retrieve_url_to_local_text_file(url: str, file_path: str) -> str:
    """Returns downloaded file contents"""
    file_path = os.path.expanduser(file_path)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with urllib.request.urlopen(url) as fr:
        pricing_info = fr.read().decode("utf-8")
    if pricing_info:
        with open(file_path, "w") as fw:
            fw.write(pricing_info)
    return pricing_info


def timed_cache(**timedelta_kwargs):
    """From https://gist.github.com/Morreski/c1d08a3afa4040815eafd3891e16b945"""

    def _wrapper(f):
        update_delta = timedelta(**timedelta_kwargs)
        next_update = datetime.utcnow() + update_delta
        # Apply @lru_cache to f with no cache size limit
        f = functools.lru_cache(None)(f)

        @functools.wraps(f)
        def _wrapped(*args, **kwargs):
            nonlocal next_update
            now = datetime.utcnow()
            if now >= next_update:
                f.cache_clear()
                next_update = now + update_delta
            return f(*args, **kwargs)

        return _wrapped

    return _wrapper


def compose_postgres_connstr_uri(
    ip_address: str,
    admin_user: str,
    admin_user_password: str = "",
    port: int = 5432,
    dbname: str = "postgres",
    sslmode="require",
) -> str:
    return f"postgresql://{admin_user}:{admin_user_password}@{ip_address}:{port}/{dbname}?sslmode={sslmode}"


def get_local_postgres_connstr() -> str:
    return "psql -h /var/run/postgresql -p 5432"


def decrypt_vault_secret(
    encrypted_value: str, vault_password_file: str
) -> str:
    if not vault_password_file or not os.path.exists(
        os.path.expanduser(vault_password_file)
    ):
        raise Exception(
            f"vault_password_file @ {vault_password_file} not found"
        )
    cmd = f"""echo -n '{encrypted_value}' | ansible-vault decrypt --vault-password-file {vault_password_file}"""
    res = subprocess.run([cmd], shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        logger.error(
            "Could not decrypt Ansible vault encoded secret with vault_password_file: %s",
            vault_password_file,
        )
        logger.error("Secret: %s", encrypted_value)
        return ""
    return res.stdout


def extract_region_from_az(az: str) -> str:
    """Special case for "local zones" a la us-west-2-lax-1a
    https://aws.amazon.com/about-aws/global-infrastructure/localzones/locations/
    """
    if len(az.split("-")) not in (3, 5):
        raise Exception("Unexpected AZ format, expecting 3 or 5 dashes")
    if len(az.split("-")) == 3:
        return az.rstrip("abcdef")
    splits = az.split("-")
    return f"{splits[0]}-{splits[1]}-{splits[2]}"


def try_rm_file_if_exists(file_path: str) -> None:
    try:
        if os.path.exists(os.path.expanduser(file_path)):
            os.unlink(os.path.expanduser(file_path))
    except Exception:
        logger.exception(f"Failed to remove file at {file_path}")


def check_ssh_ping_ok(
    login: str, host: str, private_key_file: str = ""
) -> bool:
    try:
        logger.debug("Testing SSH connection to %s@%s ...", login, host)
        ssh_args = [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-l",
            login,
        ]
        if private_key_file:
            ssh_args += ["-i", private_key_file]
        rc, _ = run_process_with_output("ssh", ssh_args + [host, "date"])
        logger.debug("Retcode: %s", rc)
        return rc == 0
    except Exception as e:
        logger.error("Failed to connect to %s@%s: %s", e)
        return False


def read_file(file_path: str) -> str:
    with open(os.path.expanduser(file_path)) as f:
        return f.read()
