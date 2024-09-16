import logging

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
