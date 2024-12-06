import logging

from pg_spot_operator.cloud_impl import aws_spot
from pg_spot_operator.cloud_impl.aws_cache import (
    get_aws_static_ondemand_pricing_info,
    get_spot_pricing_from_public_json,
)
from pg_spot_operator.cloud_impl.aws_spot import (
    get_all_ec2_spot_instance_types,
    get_all_instance_types_from_aws_regional_pricing_info,
    get_spot_instance_types_with_price_from_s3_pricing_json,
)
from pg_spot_operator.cloud_impl.cloud_structs import InstanceTypeInfo
from pg_spot_operator.cloud_impl.cloud_util import (
    extract_cpu_arch_from_sku_desc,
)
from pg_spot_operator.constants import (
    CLOUD_AWS,
    MF_SEC_VM_STORAGE_TYPE_LOCAL,
    SPOT_OPERATOR_ID_TAG,
)
from pg_spot_operator.manifests import InstanceManifest

logger = logging.getLogger(__name__)


def boto3_api_instance_list_to_instance_type_info(
    region: str, boto3_instance_type_infos: list[dict]
) -> list[InstanceTypeInfo]:
    ret = []
    for ii in boto3_instance_type_infos:
        sku = InstanceTypeInfo(
            region=region,
            cloud=CLOUD_AWS,
            instance_type=ii["InstanceType"],
            arch=extract_cpu_arch_from_sku_desc(CLOUD_AWS, ii),
        )
        sku.cpu = ii["VCpuInfo"]["DefaultVCpus"]
        sku.ram_mb = ii["MemoryInfo"]["SizeInMiB"]
        if ii.get("InstanceStorageSupported"):
            sku.instance_storage = ii.get("InstanceStorageInfo", {}).get(
                "TotalSizeInGB", 0
            )
        if ii.get("InstanceStorageInfo", {}).get("Disks"):
            sku.storage_speed_class = ii["InstanceStorageInfo"]["Disks"][0][
                "Type"
            ]
        sku.is_burstable = bool(ii.get("BurstablePerformanceSupported"))
        sku.provider_description = ii
        ret.append(sku)

    return ret


def resolve_hardware_requirements_to_instance_types(
    m: InstanceManifest,
    max_skus_to_get: int = 3,  # To be able to retry with a next instance if getting "There is no Spot capacity available"
    skus_to_avoid: list[str] | None = None,
    use_boto3: bool = True,
    regions: list[str] | None = None,
) -> list[InstanceTypeInfo]:
    """By default prefer to use the direct boto3 APIs to get the most fresh instance and pricing info.
    Use AWS static JSONs for unauthenticated price checks"""
    logger.info(
        "Resolving HW requirements in region '%s' using --selection-strategy=%s ...",
        m.region,
        m.vm.instance_selection_strategy,
    )
    logger.debug(
        "Looking for Spot VMs via %s for following HW reqs: %s",
        "boto3" if use_boto3 else "S3 price listings",
        [x for x in m.vm.dict().items() if x[1] is not None],
    )
    ret: list[InstanceTypeInfo] = []
    noinfo_regions: list[str] = []

    for region in regions or [m.region]:
        try:
            logger.debug("Processing region %s ...", region)
            if use_boto3:
                all_boto3_instance_types_for_region = (
                    get_all_ec2_spot_instance_types(
                        region,
                        with_local_storage_only=(
                            m.vm.storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL
                        ),
                    )
                )
                all_regional_spots = (
                    boto3_api_instance_list_to_instance_type_info(
                        region, all_boto3_instance_types_for_region
                    )
                )
            else:
                all_instances_for_region = (
                    get_all_instance_types_from_aws_regional_pricing_info(
                        region, get_aws_static_ondemand_pricing_info(region)
                    )
                )
                if not all_instances_for_region:
                    noinfo_regions.append(region)
                    continue
                all_spot_instances_for_region_with_price = (
                    get_spot_instance_types_with_price_from_s3_pricing_json(
                        region, get_spot_pricing_from_public_json()
                    )
                )
                if not all_spot_instances_for_region_with_price:
                    noinfo_regions.append(region)
                    continue

                all_regional_spots = []
                for x in all_instances_for_region:
                    if all_spot_instances_for_region_with_price.get(
                        x.instance_type
                    ):
                        x.hourly_spot_price = (
                            all_spot_instances_for_region_with_price[
                                x.instance_type
                            ]
                        )
                        all_regional_spots.append(x)
            ret.extend(
                aws_spot.resolve_hardware_requirements_to_instance_types(
                    all_regional_spots,
                    region,
                    max_skus_to_get,
                    use_boto3=use_boto3,
                    availability_zone=m.availability_zone,
                    cpu_min=m.vm.cpu_min,
                    cpu_max=m.vm.cpu_max,
                    ram_min=m.vm.ram_min,
                    architecture=m.vm.cpu_arch,
                    storage_type=m.vm.storage_type,
                    storage_min=m.vm.storage_min,
                    allow_burstable=m.vm.allow_burstable,
                    storage_speed_class=m.vm.storage_speed_class,
                    instance_types=m.vm.instance_types,
                    instance_types_to_avoid=skus_to_avoid,
                    instance_selection_strategy=m.vm.instance_selection_strategy,
                    instance_family=m.vm.instance_family,
                )
            )
        except Exception as e:
            noinfo_regions.append(region)
            logger.error(
                "Failed to resolve instance types from region %s: %s",
                region,
                e,
            )
    if noinfo_regions:
        logger.warning(
            "WARNING - failed to inquiry regions: %s", noinfo_regions
        )
    if not ret:
        logger.warning(
            f"No SKUs matching HW requirements found for instance {m.instance_name} in {m.cloud} region {m.region}"
        )
    return ret


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
