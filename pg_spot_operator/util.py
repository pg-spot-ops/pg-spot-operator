import datetime
import functools
import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile
from statistics import mean

import humanize
import requests

from pg_spot_operator.constants import DEFAULT_SSH_PUBKEY_PATH

logger = logging.getLogger(__name__)


def run_process_with_output(
    runnable_path: str, input_params: list[str]
) -> tuple[int, str]:
    # logger.debug("Running subprocess.Popen for: %s", [runnable_path] + input_params)
    p = subprocess.Popen(
        [runnable_path] + input_params,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    stdout, _ = p.communicate()

    return p.returncode, stdout


def merge_user_and_tuned_non_conflicting_config_params(
    config_params_tuned: dict, config_params_user: dict
) -> dict:
    """User input wins over tuned config lines in case of a collision"""

    merged = config_params_user.copy()

    for tuned_key, tuned_val in config_params_tuned.items():
        if tuned_key not in config_params_user:
            merged[tuned_key] = tuned_val

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
        update_delta = datetime.timedelta(**timedelta_kwargs)
        next_update = (
            datetime.datetime.now(datetime.timezone.utc) + update_delta
        )
        # Apply @lru_cache to f with no cache size limit
        f = functools.lru_cache(None)(f)

        @functools.wraps(f)
        def _wrapped(*args, **kwargs):
            nonlocal next_update
            now = datetime.datetime.now(datetime.timezone.utc)
            if now >= next_update:
                f.cache_clear()
                next_update = now + update_delta
            return f(*args, **kwargs)

        return _wrapped

    return _wrapper


def compose_postgres_connstr_uri(
    ip_address: str,
    admin_user: str,
    admin_password: str = "",
    port: int = 5432,
    dbname: str = "postgres",
    sslmode="require",
) -> str:
    return f"postgresql://{admin_user}:{admin_password}@{ip_address}:{port}/{dbname}?sslmode={sslmode}"


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
    login: str,
    host: str,
    private_key_file: str = "",
    max_wait_seconds: int = 60,
) -> bool:
    logger.info(
        "Testing SSH connection to %s@%s (max_wait_seconds=%s) ...",
        login,
        host,
        max_wait_seconds,
    )
    try:
        ssh_args = [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=2",
            "-l",
            login,
        ]
        if private_key_file:
            ssh_args += ["-i", private_key_file]
        rc: int = 0
        start_time: float = time.time()
        try_count: int = 0
        loop_sleep_seconds: int = 2

        while time.time() < start_time + max_wait_seconds:
            try:
                try_count += 1
                rc, _ = run_process_with_output(
                    "ssh", ssh_args + [host, "date"]
                )
                logger.debug("Try %s retcode: %s", try_count, rc)
                if rc == 0:
                    break
                else:
                    logger.debug(
                        "Sleeping %ss before retry...", loop_sleep_seconds
                    )
                    time.sleep(loop_sleep_seconds)
            except Exception:
                logger.debug(
                    "SSH ping try %s NOK with retcode: %s. Sleeping %ss",
                    try_count,
                    rc,
                    loop_sleep_seconds,
                )
                time.sleep(loop_sleep_seconds)
        return rc == 0
    except Exception as e:
        logger.error("Failed to SSH connect to %s@%s: %s", login, host, e)
        return False


def read_file(file_path: str) -> str:
    with open(os.path.expanduser(file_path)) as f:
        return f.read()


def try_download_ansible_from_github(
    tag: str, zip_url: str, config_dir: str, ansible_subdir: str = "ansible"
) -> bool:
    """Returns True on success"""
    TMP_ZIP_LOC = f"/tmp/pg-spot-operator_{tag}.zip"
    TMP_UNPACKED_PATH = f"/tmp/pg-spot-operator-{tag}"
    try:
        ansible_storage_path = os.path.expanduser(
            os.path.join(config_dir, ansible_subdir)
        )
        logger.info(
            "Downloading and extracting Ansible setup files from %s to %s",
            zip_url,
            os.path.join(config_dir, ansible_subdir),
        )

        os.makedirs(os.path.expanduser(config_dir), exist_ok=True)

        r = requests.get(zip_url, allow_redirects=True)
        if r.status_code != 200:
            logger.error("Github download failed, retcode: %s", r.status_code)
            return False
        logger.debug(
            "OK. Writing to a temp file %s ...",
            TMP_ZIP_LOC,
        )
        open(TMP_ZIP_LOC, "wb").write(r.content)

        # Unpack
        with zipfile.ZipFile(TMP_ZIP_LOC) as zip_ref:
            zip_ref.extractall("/tmp")

        logger.debug(
            "Cleaning up old Ansible files from %s if any ...",
            ansible_storage_path,
        )
        shutil.rmtree(ansible_storage_path, ignore_errors=True)
        os.makedirs(ansible_storage_path, exist_ok=True)
        # Copy only the ansible folder to ansible_storage_path
        logger.debug(
            "Copying temp Ansible files from %s to %s ...",
            os.path.join(TMP_UNPACKED_PATH, ansible_subdir),
            ansible_storage_path,
        )
        shutil.copytree(
            os.path.join(TMP_UNPACKED_PATH, ansible_subdir),
            ansible_storage_path,
            dirs_exist_ok=True,
        )

        # Clean up
        try:
            logger.debug(
                "Cleaning up the temp locations %s",
                (TMP_ZIP_LOC, TMP_UNPACKED_PATH),
            )
            os.unlink(TMP_ZIP_LOC)
            shutil.rmtree(TMP_UNPACKED_PATH, ignore_errors=True)
        except Exception:
            logger.error(
                "Failed to clean tmp Ansible files up properly from %s",
                (TMP_ZIP_LOC, TMP_UNPACKED_PATH),
            )
    except Exception:
        logger.exception(
            f"Failed to download the repo from Github URL: {zip_url}"
        )
        return False
    return True


def get_aws_region_code_to_name_mapping() -> dict:
    """Based on https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-regions-availability-zones.html#concepts-available-regions
    Europe -> EU to match on-demand pricing info at https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/metadata.json
    PS Needs reviewing / updating time to time!!! Last checked 2024-11-15
    Just copy-pasted from browser, the "^I" char seems funnily to be a tab also https://stackoverflow.com/questions/65943518/what-is-the-i-carat-capital-i-character-in-python
    """
    raw = """
us-east-1	US East (N. Virginia)	Not required
us-east-2	US East (Ohio)	Not required
us-west-1	US West (N. California)	Not required
us-west-2	US West (Oregon)	Not required
af-south-1	Africa (Cape Town)	Required
ap-east-1	Asia Pacific (Hong Kong)	Required
ap-south-2	Asia Pacific (Hyderabad)	Required
ap-southeast-3	Asia Pacific (Jakarta)	Required
ap-southeast-5	Asia Pacific (Malaysia)	Required
ap-southeast-4	Asia Pacific (Melbourne)	Required
ap-south-1	Asia Pacific (Mumbai)	Not required
ap-northeast-3	Asia Pacific (Osaka)	Not required
ap-northeast-2	Asia Pacific (Seoul)	Not required
ap-southeast-1	Asia Pacific (Singapore)	Not required
ap-southeast-2	Asia Pacific (Sydney)	Not required
ap-northeast-1	Asia Pacific (Tokyo)	Not required
ca-central-1	Canada (Central)	Not required
ca-west-1	Canada West (Calgary)	Required
cn-north-1	China (Beijing)	Not required
cn-northwest-1	China (Ningxia)	Not required
eu-central-1	Europe (Frankfurt)	Not required
eu-west-1	Europe (Ireland)	Not required
eu-west-2	Europe (London)	Not required
eu-south-1	Europe (Milan)	Required
eu-west-3	Europe (Paris)	Not required
eu-south-2	Europe (Spain)	Required
eu-north-1	Europe (Stockholm)	Not required
eu-central-2	Europe (Zurich)	Required
il-central-1	Israel (Tel Aviv)	Required
me-south-1	Middle East (Bahrain)	Required
me-central-1	Middle East (UAE)	Required
sa-east-1	South America (São Paulo)	Not required
"""
    ret: dict = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        splits = line.split("\t")
        if len(splits) < 2:
            continue
        ret[splits[0].strip()] = splits[1].replace("Europe", "EU").strip()
    return ret


def region_regex_to_actual_region_codes(region_regex: str) -> list[str]:
    """Empty / no input = all regions"""
    if not region_regex or region_regex.strip() == "":
        return sorted(list(get_aws_region_code_to_name_mapping().keys()))

    r = re.compile(region_regex, re.IGNORECASE)
    ret: list[str] = []

    for code, name in get_aws_region_code_to_name_mapping().items():
        if r.search(code) or r.search(name):
            ret.append(code)
    return sorted(ret)


def space_pad_manifest(mfs: str, spaces_to_add: int = 2) -> str:
    """Add two leading spaces so that the manifest could be sub-keyed for Ansible vars merging
    Remove YAML --- markers if present
    """
    splits = mfs.splitlines()
    new_splits = [
        " " * spaces_to_add + s for s in splits if s.strip() != "---"
    ]
    return "\n".join(new_splits)


def timestamp_to_human_readable_delta(
    dt1: datetime.datetime | None, dt2: datetime.datetime | None = None
) -> str:
    if not dt1:
        return "N/A"

    if not dt2:
        dt2 = datetime.datetime.now(datetime.timezone.utc)
    return humanize.naturaldelta(dt2 - dt1)


def extract_numbers_from_string(input: str) -> list[float]:
    pattern = r"(\d+(?:\.\d+)?)"
    matches = re.findall(pattern, input)
    return [float(match) for match in matches]


def extract_mtf_months_from_eviction_rate_group_label(
    ev_rate_range: str,
) -> int:
    """Months until get a 50% chance to get evicted
    10-15% -> 12.5 -> 50 / 12.5 = 4mons
    Special case: >20% = 0
    """
    evic_rate_percentages = extract_numbers_from_string(ev_rate_range)
    if len(evic_rate_percentages) > 1:
        avg_evic_rate = mean(evic_rate_percentages)
    else:
        avg_evic_rate = evic_rate_percentages[0]
    if avg_evic_rate >= 20:
        return 0
    return round(50 / avg_evic_rate)


def check_default_ssh_key_exists_and_readable() -> bool:
    default_ssh_pubkey_path = os.path.expanduser(DEFAULT_SSH_PUBKEY_PATH)
    try:
        if os.path.exists(default_ssh_pubkey_path):
            with open(default_ssh_pubkey_path) as f:
                kd = f.read()
                if kd:
                    return True
        return False
    except Exception:
        logger.debug(
            "No default SSH key found at default location: %s",
            DEFAULT_SSH_PUBKEY_PATH,
        )
        return False


def pg_size_bytes(size_str: str) -> int:
    """Reimplement PG-s pg_size_bytes basically. 1024 based!
    https://pgpedia.info/p/pg_size_bytes.html
    """
    size_units = {
        "bytes": 1,
        "byte": 1,
        "kb": 1024,
        "k": 1024,
        "mb": 1024**2,
        "m": 1024**2,
        "gb": 1024**3,
        "g": 1024**3,
        "tb": 1024**4,
        "t": 1024**4,
        "pb": 1024**5,
        "p": 1024**5,
    }
    size_str = size_str.lower()
    # Regular expression to match the size format
    match = re.match(r"^\s*([\d.]+)\s*([a-zA-Z]*)\s*$", size_str)
    if not match:
        raise ValueError(f"Invalid size format: {size_str}")

    value, unit = match.groups()
    value = float(value)  # Convert the numeric part to a float
    unit = unit.lower() if unit else "bytes"  # Default unit is bytes

    if unit not in size_units:
        raise ValueError(f"Unknown size unit: {unit}")

    # Convert to bytes
    return int(value * size_units[unit])
