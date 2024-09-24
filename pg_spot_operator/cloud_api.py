import logging

from pg_spot_operator.cloud_impl import aws_spot
from pg_spot_operator.cloud_impl.cloud_structs import ResolvedInstanceTypeInfo
from pg_spot_operator.constants import CLOUD_AWS, SPOT_OPERATOR_ID_TAG
from pg_spot_operator.manifests import InstanceManifest

logger = logging.getLogger(__name__)


def get_cheapest_skus_for_hardware_requirements(
    m: InstanceManifest,
    max_skus_to_get: int = 1,
    skus_to_avoid: list[str] | None = None,
) -> list[ResolvedInstanceTypeInfo]:
    logger.debug(
        "Looking for the cheapest Spot VM for following HW reqs: %s",
        [x for x in m.vm.dict().items() if x[1] is not None],
    )
    if m.cloud == CLOUD_AWS:
        return aws_spot.get_cheapest_sku_for_hw_reqs(
            max_skus_to_get,
            m.region,
            availability_zone=m.availability_zone,
            cpu_min=m.vm.cpu_min,
            cpu_max=m.vm.cpu_max,
            ram_min=m.vm.ram_min,
            architecture=m.vm.cpu_architecture,
            storage_type=m.vm.storage_type,
            storage_min=m.vm.storage_min,
            allow_burstable=m.vm.allow_burstable,
            storage_speed_class=m.vm.storage_speed_class,
            instance_types_to_avoid=skus_to_avoid,
        )
    return []


def get_all_operator_vms_in_manifest_region(
    m: InstanceManifest,
) -> dict[str, dict]:
    vms_in_region: dict[str, dict] = {}
    if m.cloud == CLOUD_AWS:
        aws_vms = aws_spot.get_all_active_operator_instances_from_region(
            m.region
        )
        for vm in aws_vms:
            for tag in vm["Tags"]:
                if tag["Key"] == SPOT_OPERATOR_ID_TAG:
                    vms_in_region[tag["Value"]] = vm
    return vms_in_region


def try_get_monthly_ondemand_price_for_sku(
    cloud: str, region: str, sku: str
) -> float:
    hourly: float = 0
    try:
        if cloud == CLOUD_AWS:
            hourly = aws_spot.get_current_hourly_ondemand_price(region, sku)
        return round(hourly * 24 * 30, 1)
    except Exception:
        return 0
