import logging

from pg_spot_operator.cloud_impl import aws_spot
from pg_spot_operator.cloud_impl.aws_spot import get_current_hourly_spot_price
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
        "Looking for Spot VMs for following HW reqs: %s",
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
            instance_selection_strategy=m.vm.instance_selection_strategy,
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


def get_cheapest_instance_type_from_selection(
    cloud: str,
    instance_types: list[str],
    region: str,
    availability_zone: str = "",
) -> str:
    logger.debug("Spot price comparing instance types: %s ...", instance_types)
    cheapest_instance = ""
    cheapest_price = 1e6

    if cloud == CLOUD_AWS:
        for ins_type in instance_types:
            price = get_current_hourly_spot_price(
                region, ins_type, availability_zone
            )
            logger.debug("%s at $ %s", ins_type, price)
            if price < cheapest_price:
                cheapest_price = price
                cheapest_instance = ins_type
        logger.debug(
            "Cheapest instance: %s at $ %s", cheapest_instance, cheapest_price
        )
        return cheapest_instance
    raise NotImplementedError
