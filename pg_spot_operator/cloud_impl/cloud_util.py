import logging
import re

from pg_spot_operator.constants import (
    CLOUD_AWS,
    CLOUD_AZURE,
    CLOUD_GCP,
    CLOUD_VAGRANT_LIBVIRT,
    CPU_ARCH_ARM,
    CPU_ARCH_X86,
)

logger = logging.getLogger(__name__)


def extract_cpu_arch_from_sku_desc(cloud: str, i_desc: dict) -> str:
    """Extract CPU arch and unify to: arm | x86"""
    if cloud == CLOUD_VAGRANT_LIBVIRT:
        return CPU_ARCH_X86  # Not relevant for local
    if (
        cloud == CLOUD_GCP
    ):  # No arch attribute seems...based on machine_type name only (list needs to be updated time to time!)
        if (
            i_desc["name"].startswith("n2d")  # As of 2024-07-08
            or i_desc["name"].startswith("t2d")
            or i_desc["name"].startswith("t2a")
        ):
            return CPU_ARCH_ARM
        else:
            return CPU_ARCH_X86

    arch_str: str = ""

    if cloud == CLOUD_AWS:
        arch_str = i_desc["ProcessorInfo"]["SupportedArchitectures"][0]
    elif cloud == CLOUD_AZURE:
        for cap in i_desc["capabilities"]:
            if cap["name"] == "CpuArchitectureType":
                arch_str = cap["value"]
                break

    if not arch_str:
        raise Exception(
            f"Could not infer CPU architecture from cloud {cloud}, SKU: {i_desc}"
        )
    arch_str = arch_str.lower()
    if "arm" in arch_str:
        return CPU_ARCH_ARM
    else:
        return CPU_ARCH_X86


def infer_cpu_arch_from_aws_instance_type_name(instance_type: str) -> str:
    """Defaults to x86"""
    if instance_type:
        splits = instance_type.split(".")
        if len(splits) == 2 and "g" in splits[0]:
            return CPU_ARCH_ARM
    return CPU_ARCH_X86


def parse_aws_pricing_json_storage_string(
    storage_string: str,
) -> tuple[int, str]:
    if "EBS only" in storage_string:
        return 0, ""
    if " x " in storage_string:
        # "2 x 1900 NVMe SSD"
        splits = storage_string.split(" x ")
        if len(splits) != 2:
            logger.error(
                "Unexpected EC2 storage string, can't parse size / type, not assuming any local storage. %s",
                storage_string,
            )
            return 0, ""
        multiplier = int(splits[0])
        m = re.match(r"^\s*(\d+)\s*(.*)$", splits[1])
        if not m or len(m.groups()) != 2:
            logger.error(
                "Unexpected EC2 storage string, can't parse size / type, not assuming any local storage. %s",
                storage_string,
            )
            return 0, ""
        size = int(m.group(1)) if m.group(1) else 0
        storage_speed_class = "hdd"
        if m.group(2):
            storage_speed_class = (
                "nvme"
                if "nvme" in m.group(2).lower()
                else "ssd" if "ssd" in m.group(2).lower() else "hdd"
            )
        return multiplier * size, storage_speed_class
    else:
        # "125 GB NVMe SSD"
        m = re.match(r"^\s*(\d+)\s*(.*)$", storage_string)
        if not m or len(m.groups()) != 2:
            logger.error(
                "Unexpected EC2 storage string, can't parse size / type, not assuming any local storage. %s",
                storage_string,
            )
            return 0, ""
        size = int(m.group(1))
        storage_speed_class = "hdd"
        if m.group(2):
            storage_speed_class = (
                "nvme"
                if "nvme" in m.group(2).lower()
                else "ssd" if "ssd" in m.group(2).lower() else "hdd"
            )
        return size, storage_speed_class


def extract_instance_storage_size_and_type_from_aws_pricing_storage_string(
    storage_string: str,
) -> tuple[int, str]:
    r"""Storage strings look something like:
    http "https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/EU%20(Stockholm)/Linux/index.json" \
      | jq | grep '"Storage":'  | sed 's/^[ \t]*\(.*[^ \t]\)[ \t]*$/\1/'  | sort | uniq
    ...
    "Storage": "8 x 7500 NVMe SSD",
    "Storage": "8 x 940 NVMe SSD",
    "Storage": "900 GB NVMe SSD",
    "Storage": "EBS only",
    """
    if "EBS only" in storage_string:
        return 0, ""
    if " x " in storage_string:
        # "2 x 1900 NVMe SSD"
        splits = storage_string.split(" x ")
        if len(splits) != 2:
            logger.error(
                "Unexpected EC2 storage string, can't parse size / type, not assuming any local storage. %s",
                storage_string,
            )
            return 0, ""
        multiplier = int(splits[0])
        m = re.match(r"^\s*(\d+)\s*(.*)$", splits[1])
        if not m or len(m.groups()) != 2:
            logger.error(
                "Unexpected EC2 storage string, can't parse size / type, not assuming any local storage. %s",
                storage_string,
            )
            return 0, ""
        size = int(m.group(1)) if m.group(1) else 0
        storage_speed_class = "hdd"
        if m.group(2):
            storage_speed_class = (
                "nvme"
                if "nvme" in m.group(2).lower()
                else "ssd" if "ssd" in m.group(2).lower() else "hdd"
            )
        return multiplier * size, storage_speed_class
    else:
        # "125 GB NVMe SSD"
        m = re.match(r"^\s*(\d+)\s*(.*)$", storage_string)
        if not m or not m.group(1):
            logger.error(
                "Unexpected EC2 storage string, can't parse size / type, not assuming any local storage. %s",
                storage_string,
            )
            return 0, ""
        size = int(m.group(1))
        storage_speed_class = "hdd"
        if m.group(2):
            storage_speed_class = (
                "nvme"
                if "nvme" in m.group(2).lower()
                else "ssd" if "ssd" in m.group(2).lower() else "hdd"
            )
        return size, storage_speed_class


def is_explicit_aws_region_code(region: str) -> bool:
    """eu-north-1 for example is explicit"""
    if not region or not region.strip():
        return False
    return len(region.split("-")) == 3 and "|" not in region


def extract_instance_family_from_instance_type_code(instance_type: str) -> str:
    """i4g.2xlarge -> i4g"""
    if not instance_type or "." not in instance_type:
        raise Exception(
            f"Unexpected instance_type input - expecting '.' as family separator. Got: {instance_type}"
        )
    return instance_type.strip().lower().split(".")[0]
