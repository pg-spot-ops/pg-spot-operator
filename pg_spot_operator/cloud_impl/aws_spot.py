import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean

import requests
from botocore.exceptions import EndpointConnectionError

from pg_spot_operator.cloud_impl.aws_cache import (
    get_aws_static_ondemand_pricing_info,
    get_spot_eviction_rates_from_public_json,
    get_spot_pricing_from_public_json,
)
from pg_spot_operator.cloud_impl.aws_client import get_client
from pg_spot_operator.cloud_impl.cloud_structs import (
    EvictionRateInfo,
    InstanceTypeInfo,
)
from pg_spot_operator.cloud_impl.cloud_util import (
    extract_cpu_arch_from_sku_desc,
    extract_instance_storage_size_and_type_from_aws_pricing_storage_string,
    infer_cpu_arch_from_aws_instance_type_name,
)
from pg_spot_operator.constants import (
    CLOUD_AWS,
    MF_SEC_VM_STORAGE_TYPE_LOCAL,
    SPOT_OPERATOR_ID_TAG,
)
from pg_spot_operator.instance_type_selection import (
    SELECTION_STRATEGY_BALANCED,
    SELECTION_STRATEGY_EVICTION_RATE,
    InstanceTypeSelection,
)
from pg_spot_operator.util import timed_cache

MAX_SKUS_FOR_SPOT_PRICE_COMPARE = 15
SPOT_HISTORY_LOOKBACK_DAYS = 1


logger = logging.getLogger(__name__)
# Reduce boto noisiness https://github.com/boto/boto3/issues/521#issuecomment-653060090
logging.getLogger("boto3").setLevel(logging.ERROR)
logging.getLogger("botocore").setLevel(logging.ERROR)
logging.getLogger("nose").setLevel(logging.ERROR)
logging.getLogger("s3transfer").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)


@timed_cache(seconds=3600)
def describe_instance_type_boto3(instance_type: str, region: str) -> dict:
    try:
        client = get_client("ec2", region)
        resp = client.describe_instance_types(InstanceTypes=[instance_type])
        if resp:
            return resp["InstanceTypes"][0]
    except Exception:
        logger.exception(
            f"Failed to describe instance {instance_type} in region {region}"
        )
    return {}


def try_get_monthly_ondemand_price_for_sku(region: str, sku: str) -> float:
    hourly: float = 0
    try:
        hourly = get_current_hourly_ondemand_price(region, sku)
        return (
            round(hourly * 24 * 30, 1)
            if hourly * 24 * 30 < 100
            else round(hourly * 24 * 30)
        )
    except Exception as e:
        logger.error(
            "Failed to get ondemand instance pricing from AWS, trying ec2.shop fallback. Error: %s",
            e,
        )
    try:
        hourly = get_current_hourly_ondemand_price_fallback(region, sku)
        return (
            round(hourly * 24 * 30, 1)
            if hourly * 24 * 30 < 100
            else round(hourly * 24 * 30)
        )
    except Exception as e:
        logger.error(
            "Failed to get fallback pricing from ec2.shop. Error: %s", e
        )
    return 0


def resolve_instance_type_info(
    instance_type: str, region: str, zone: str = "", i_desc: dict | None = None
) -> InstanceTypeInfo:
    """i_desc = AWS API response dict. e.g.: aws ec2 describe-instance-types --instance-types i3en.xlarge"""
    if not i_desc:
        logger.debug(
            "Describing instance type %s in region %s ...",
            instance_type,
            region,
        )
        i_desc = describe_instance_type_boto3(instance_type, region)
    if not i_desc:
        raise Exception(
            f"Could not describe instance type {instance_type} in region {region}"
        )
    return InstanceTypeInfo(
        instance_type=instance_type,
        arch=extract_cpu_arch_from_sku_desc(CLOUD_AWS, i_desc),
        cloud=CLOUD_AWS,
        region=region,
        availability_zone=zone,
        cpu=i_desc.get("VCpuInfo", {}).get("DefaultVCpus", 0),
        ram_mb=i_desc.get("MemoryInfo", {}).get("SizeInMiB", 0),
        instance_storage=i_desc.get("InstanceStorageInfo", {}).get(
            "TotalSizeInGB", 0
        ),
        storage_speed_class=i_desc.get("InstanceStorageInfo", {}).get(
            "Disks", [{"Type": "hdd"}]
        )[0]["Type"],
    )


@timed_cache(seconds=3600)
def get_all_ec2_spot_instance_types(
    region: str, with_local_storage_only: bool = False
):
    client = get_client("ec2", region)
    instances = []
    filters = [
        {
            "Name": "supported-usage-class",
            "Values": [
                "spot",
            ],
        },
    ]
    if with_local_storage_only:
        filters.append(
            {
                "Name": "instance-storage-supported",
                "Values": [
                    "true",
                ],
            }
        )

    paginator = client.get_paginator("describe_instance_types")

    page_iterator = paginator.paginate(Filters=filters)

    for page in page_iterator:
        instances.extend(page["InstanceTypes"])

    logger.debug(
        "%s total instance types found for region %s via describe_instance_types. with_local_storage_only=%s",
        len(instances),
        region,
        with_local_storage_only,
    )
    return instances


@timed_cache(seconds=600)
def get_current_hourly_spot_price_static(
    region: str,
    instance_type: str,
) -> float:
    try:
        all_spot_instances_for_region_with_price = (
            get_spot_instance_types_with_price_from_s3_pricing_json(
                region, get_spot_pricing_from_public_json()
            )
        )
        if not all_spot_instances_for_region_with_price:
            logger.warning(
                "Couldn't fetch Spot price for %s in region %s from static files",
                instance_type,
                region,
            )
            return 0

        if instance_type not in all_spot_instances_for_region_with_price:
            logger.warning(
                "Instance %s pricing data not found from static Spot price files in region %s",
                instance_type,
                region,
            )
            return 0
        logger.debug(
            "Hourly Spot price of %s determined for %s in region %s from static pricing files",
            all_spot_instances_for_region_with_price[instance_type],
            instance_type,
            region,
        )
        return all_spot_instances_for_region_with_price[instance_type]
    except Exception:
        logger.exception(
            "Couldn't fetch Spot price for %s in region %s from static files",
            instance_type,
            region,
        )
    return 0


# TODO some caching
def get_current_hourly_spot_price_boto3(
    region: str,
    instance_type: str,
    az: str = "",
    pricing_data: list[dict] | None = None,
) -> float:
    """Assuming here that the API returns latest data first"""
    if not pricing_data:
        pricing_data = get_spot_pricing_data_for_skus_over_period(
            [instance_type], region, timedelta(days=1), az=az
        )
    if az:
        for pd in pricing_data:
            if (
                pd["AvailabilityZone"] == az
                and pd["InstanceType"] == instance_type
            ):
                return float(pd["SpotPrice"])
    else:  # Look for cheapest AZ
        avg_by_sku_az = (
            get_avg_spot_price_from_pricing_history_data_by_sku_and_az(
                pricing_data
            )
        )
        _, _, price = avg_by_sku_az[0]
        return price

    return 0


def get_ondemand_price_for_instance_type_from_aws_regional_pricing_info(
    region: str, instance_type: str, regional_pricing_info: dict
) -> float:

    for reg, reg_data in regional_pricing_info.get("regions", {}).items():
        for _, sku_data in reg_data.items():

            if sku_data.get("Instance Type") == instance_type:
                return float(sku_data.get("price", 0))

    logger.error(
        "Failed to find ondemand pricing info from AWS regional data for region %s, instance type %s",
        region,
        instance_type,
    )
    return 0


@timed_cache(seconds=1800)
def get_current_hourly_ondemand_price(
    region: str,
    instance_type: str,
) -> float:
    ondemand_pricing_info = get_aws_static_ondemand_pricing_info(region)
    if not ondemand_pricing_info:
        return 0
    return get_ondemand_price_for_instance_type_from_aws_regional_pricing_info(
        region, instance_type, ondemand_pricing_info
    )


def get_current_hourly_ondemand_price_fallback(
    region: str,
    instance_type: str,
) -> float:
    """Use an external 3rd party web service as fallback if something changes in AWS static pricing JSONs"""
    url = f"https://ec2.shop/?region={region}&filter={instance_type}"
    f = requests.get(
        url, headers={"Content-Type": "application/json"}, timeout=5
    )
    if f.status_code != 200:
        return 0
    pd = f.json()
    if not pd["Prices"]:
        return 0
    return round(pd["Prices"][0]["Cost"], 6)


def filter_instance_types_by_hw_req(
    all_instances: list[InstanceTypeInfo],
    cpu_min: int | None = 0,
    cpu_max: int | None = 0,
    ram_min: int | None = 0,
    cpu_arch: str = "",
    storage_min: int | None = 0,
    storage_type: str = "network",
    allow_burstable: bool = True,
    storage_speed_class: str | None = "any",
    instance_types: list[str] | None = None,
    instance_types_to_avoid: list[str] | None = None,
    instance_family: str = "",
) -> list[InstanceTypeInfo]:
    """Returns qualified SKUs sorted by (CPU, RAM) or (CPU, Total instance storage DESC)"""
    ret: list[InstanceTypeInfo] = []
    instance_family_regex: re.Pattern | None = None

    if instance_types:
        logger.debug(
            "Only considering following instance types: %s",
            instance_types,
        )
    if instance_family:
        logger.debug(
            "Only considering instance families matching regex: %s",
            instance_family,
        )
        instance_family_regex = re.compile(instance_family)
    if instance_types_to_avoid:
        logger.debug(
            "NOT considering following instance types: %s",
            instance_types_to_avoid,
        )

    for ii in all_instances:

        if instance_types:
            if ii.instance_type not in instance_types:
                continue
            ret.append(ii)
            continue

        if (
            instance_types_to_avoid
            and ii.instance_type in instance_types_to_avoid
        ):
            continue

        if (
            instance_family
            and instance_family_regex
            and not instance_family_regex.search(ii.instance_type)
        ):
            continue

        if cpu_arch and cpu_arch.strip() and cpu_arch.strip().lower() != "any":
            # On AWS architectures are named x86_64 and arm64, but we only look for arm / not-arm for now
            if "arm" in cpu_arch.strip().lower() and "arm" not in ii.arch:
                continue
            if "arm" not in cpu_arch.strip().lower() and "arm" in ii.arch:
                continue

        if allow_burstable is False and ii.is_burstable:
            continue

        if cpu_min and ii.cpu < cpu_min:
            continue

        if cpu_max and ii.cpu > cpu_max:
            continue

        if ram_min and ii.ram_mb / 1000 < ram_min:  # User input in GBs
            continue

        if (
            storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL
            and ii.instance_storage == 0
        ):
            continue

        if storage_min and storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL:
            if ii.instance_storage < storage_min:
                continue

        if (
            storage_speed_class
        ):  # PS storage_speed_class=ssd > SSD + NVME, storage_speed_class=nvme > nvme only
            if (
                storage_speed_class == "hdd"
                and ii.storage_speed_class != "hdd"
            ):
                continue
            if (
                storage_speed_class == "nvme"
                and ii.storage_speed_class != "nvme"
            ):
                continue

        ret.append(ii)

    if (
        storage_min and storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL
    ):  # Prefer bigger disks for local storage
        ret.sort(
            key=lambda x: (
                x.cpu,
                x.instance_storage,
            )
        )
    else:
        ret.sort(
            key=lambda x: (
                x.cpu,
                x.ram_mb,
            )
        )
    return ret


def get_spot_pricing_data_for_skus_over_period(
    instance_types: list[str],
    region: str,
    lookback_period: timedelta,
    az: str | None = None,
) -> list[dict]:
    """
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_spot_price_history.html
    Response: [
    {'AvailabilityZone': 'eu-north-1b', 'InstanceType': 'g5.2xlarge', 'ProductDescription': 'Linux/UNIX', 'SpotPrice': '0.576800', 'Timestamp': datetime.datetime(2024, 5, 8, 8, 16, 35, tzinfo=tzutc())},
    {'AvailabilityZone': 'eu-north-1b', 'InstanceType': 'm7gd.xlarge', 'ProductDescription': 'Linux/UNIX', 'SpotPrice': '0.041700', 'Timestamp': datetime.datetime(2024, 5, 8, 7, 1, 35, tzinfo=tzutc())},
    {'AvailabilityZone': 'eu-north-1c', 'InstanceType': 'g5.2xlarge', 'ProductDescription': 'Linux/UNIX', 'SpotPrice': '0.562100', 'Timestamp': datetime.datetime(2024, 5, 8, 6, 32, 22, tzinfo=tzutc())},
    {'AvailabilityZone': 'eu-north-1c', 'InstanceType': 'm7gd.xlarge', 'ProductDescription': 'Linux/UNIX', 'SpotPrice': '0.048800', 'Timestamp': datetime.datetime(2024, 5, 8, 6, 1, 45, tzinfo=tzutc())}
    ]
    """
    client = get_client("ec2", region)
    filters = [
        {"Name": "instance-type", "Values": instance_types},
        {"Name": "product-description", "Values": ["Linux/UNIX"]},
    ]
    kwargs = {}
    if az:
        kwargs["AvailabilityZone"] = az

    paginator = client.get_paginator("describe_spot_price_history")
    page_iterator = paginator.paginate(
        Filters=filters,
        StartTime=(datetime.utcnow() - lookback_period),
        **kwargs,
    )
    pricing_data = []
    for page in page_iterator:
        pricing_data.extend(page["SpotPriceHistory"])
    return pricing_data


def get_avg_spot_price_from_pricing_history_data_by_sku_and_az(
    pricing_data: list[dict],
) -> list[tuple[str, str, float]]:
    """Returns SKUs by az and price, cheapest first"""

    per_sku_az_hist: dict[str, dict[str, list]] = defaultdict(
        lambda: defaultdict(list)
    )
    ret: list[tuple[str, str, float]] = []

    for pd in pricing_data:
        per_sku_az_hist[pd["InstanceType"]][pd["AvailabilityZone"]].append(
            float(pd["SpotPrice"])
        )
    for sku, az_dict in per_sku_az_hist.items():
        for az, price_data in az_dict.items():
            avg_price = mean(price_data)
            ret.append((sku, az, round(avg_price, 6)))

    return sorted(ret, key=lambda x: x[2])


def get_filtered_instances_by_price_no_az(
    filtered_instances_by_cpu: list[InstanceTypeInfo],
) -> list[tuple[str, str, float]]:
    """Static S3 Spot JSONs show the price of the cheapest AZ sadly without mentioning it"""
    by_cpu = [
        (x.instance_type, "", x.hourly_spot_price)
        for x in filtered_instances_by_cpu
    ]
    return sorted(by_cpu, key=lambda x: x[2])


def attach_pricing_info_to_instance_type_info(
    instance_types: list[InstanceTypeInfo],
) -> list[InstanceTypeInfo]:
    for iti in instance_types:
        if not iti.hourly_spot_price:
            if (
                iti.availability_zone
            ):  # AWS provided static pricing is not zonal sadly ...
                iti.hourly_spot_price = get_current_hourly_spot_price_boto3(
                    region=iti.region,
                    instance_type=iti.instance_type,
                    az=iti.availability_zone,
                )
            else:
                iti.hourly_spot_price = get_current_hourly_spot_price_static(
                    region=iti.region,
                    instance_type=iti.instance_type,
                )
        if not iti.monthly_spot_price:
            iti.monthly_spot_price = (
                round(iti.hourly_spot_price * 24 * 30, 1)
                if iti.hourly_spot_price * 24 * 30 < 100
                else round(iti.hourly_spot_price * 24 * 30)
            )
        if not iti.hourly_ondemand_price:
            iti.monthly_ondemand_price = (
                try_get_monthly_ondemand_price_for_sku(
                    iti.region, iti.instance_type
                )
            )

    return instance_types


def resolve_hardware_requirements_to_instance_types(
    all_instances: list[InstanceTypeInfo],
    region: str,
    max_skus_to_get: int,
    use_boto3: bool = False,
    availability_zone: str | None = None,
    cpu_min: int = 0,
    cpu_max: int = 0,
    ram_min: int = 0,
    architecture: str = "any",
    storage_type: str = "network",
    storage_min: int = 0,
    allow_burstable: bool = True,
    storage_speed_class: str = "any",
    instance_types: list[str] | None = None,
    instance_types_to_avoid: list[str] | None = None,
    instance_selection_strategy: str = "cheapest",
    instance_family: str = "",
) -> list[InstanceTypeInfo]:
    """Returns a price-sorted list"""
    if not all_instances:
        raise Exception("Need all_instances set to apply a selection strategy")

    logger.debug(
        "Filtering through %s instances types to match HW reqs ...",
        len(all_instances),
    )
    qualified_instances_cpu_sorted: list[InstanceTypeInfo] = (
        filter_instance_types_by_hw_req(
            all_instances,
            cpu_min=cpu_min,
            cpu_max=cpu_max,
            ram_min=ram_min,
            cpu_arch=architecture,
            storage_min=storage_min,
            storage_type=storage_type,
            allow_burstable=allow_burstable,
            storage_speed_class=storage_speed_class,
            instance_types=instance_types,
            instance_types_to_avoid=instance_types_to_avoid,
            instance_family=instance_family,
        )
    )

    logger.debug(
        "%s of them matching min HW reqs", len(qualified_instances_cpu_sorted)
    )

    if not qualified_instances_cpu_sorted:
        return []

    if len(qualified_instances_cpu_sorted) > MAX_SKUS_FOR_SPOT_PRICE_COMPARE:
        logger.debug(
            "Reducing to %s instance types by CPU count to reduce pricing history fetching",
            MAX_SKUS_FOR_SPOT_PRICE_COMPARE,
        )
        qualified_instances_cpu_sorted = qualified_instances_cpu_sorted[
            :MAX_SKUS_FOR_SPOT_PRICE_COMPARE
        ]

    instance_types_to_consider = [
        x.instance_type for x in qualified_instances_cpu_sorted
    ]
    avg_by_sku_az: list[tuple[str, str, float]] = (
        []
    )  # [(i3.xlarge, eu-north-1, 0.0132),]

    qualified_instances_with_price_info: list[InstanceTypeInfo] = []

    if use_boto3:
        hourly_pricing_data = get_spot_pricing_data_for_skus_over_period(
            instance_types_to_consider,
            region,
            timedelta(days=SPOT_HISTORY_LOOKBACK_DAYS),
            availability_zone,
        )
        if not hourly_pricing_data:
            raise Exception(
                "Could not fetch pricing data, can't select SKU"
            )  # TODO use last cached data
        avg_by_sku_az = (
            get_avg_spot_price_from_pricing_history_data_by_sku_and_az(
                hourly_pricing_data
            )
        )

        if (
            availability_zone
        ):  # avg_by_sku_az and qualified_instances_by_cpu should map 1-to-1
            avg_by_sku_az_map: dict[str, float] = {
                ins_type: price for ins_type, _, price in avg_by_sku_az
            }
            for qi in qualified_instances_cpu_sorted:
                if qi.instance_type in avg_by_sku_az_map:
                    qi.hourly_spot_price = avg_by_sku_az_map[qi.instance_type]
                    qi.region = region
                    qi.availability_zone = availability_zone or ""
            qualified_instances_with_price_info = (
                qualified_instances_cpu_sorted
            )
        else:
            # If user doesn't fix AZ, instance type infos will "multiply" as get price per AZ
            qualified_instances_map: dict[str, InstanceTypeInfo] = {
                x.instance_type: x for x in qualified_instances_cpu_sorted
            }

            for ins_type, az, spot_price in avg_by_sku_az:
                qiti: InstanceTypeInfo = qualified_instances_map[ins_type]
                qiti_az = InstanceTypeInfo(**qiti.__dict__)
                qiti_az.availability_zone = az
                qiti_az.hourly_spot_price = spot_price
                qualified_instances_with_price_info.append(qiti_az)
    else:
        qualified_instances_with_price_info = qualified_instances_cpu_sorted
        # Already have a price in InstanceTypeInfo when using public AWS pricing API, just for showing the candidates
        avg_by_sku_az = get_filtered_instances_by_price_no_az(
            qualified_instances_cpu_sorted
        )

    try:
        qualified_instances_with_price_info = (
            add_eviction_rate_to_instance_types(
                region, qualified_instances_with_price_info
            )
        )
    except Exception:
        if instance_selection_strategy in (
            SELECTION_STRATEGY_EVICTION_RATE,
            SELECTION_STRATEGY_BALANCED,
        ):  # Can't proceed, for other strategies not critical
            raise
        logger.warning(
            "Could not fetch eviction rate information from AWS, can't display expected eviction rate info"
        )

    logger.debug("Instances / Prices in selection: %s", avg_by_sku_az)

    instance_selection_strategy_cls = (
        InstanceTypeSelection.get_selection_strategy(
            instance_selection_strategy
        )
    )
    logger.debug(
        "Applying instance selection strategy: %s ...",
        instance_selection_strategy,
    )

    strategy_sorted_instance_types = instance_selection_strategy_cls.execute(
        qualified_instances_with_price_info
    )
    if not strategy_sorted_instance_types:
        raise Exception("Should not happen")

    strategy_sorted_instance_types_with_pricing = (
        attach_pricing_info_to_instance_type_info(
            strategy_sorted_instance_types
        )
    )

    return strategy_sorted_instance_types_with_pricing[:max_skus_to_get]


@timed_cache(seconds=30)
def get_all_active_operator_instances_from_region(
    region: str,
) -> list[dict]:
    instances = []

    logger.debug(
        "Fetching all operator instances from AWS region %s ...", region
    )
    client = get_client("ec2", region)
    filters = [
        {
            "Name": "instance-state-name",
            "Values": ["pending", "running", "stopping", "stopped"],
        },
        {"Name": "tag-key", "Values": [SPOT_OPERATOR_ID_TAG]},
    ]

    paginator = client.get_paginator("describe_instances")

    page_iterator = paginator.paginate(Filters=filters)

    for page in page_iterator:
        for r in page.get("Reservations", []):
            if r.get("Instances"):
                instances.extend(r["Instances"])
    logger.debug("%s found", len(instances))
    return instances


@timed_cache(seconds=5)
def get_backing_vms_for_instances_if_any(
    region: str, instance_name: str
) -> list[dict]:
    instances = []
    try:
        logger.debug(
            "Fetching all non-terminated/terminating instances for instance %s in AWS region %s ...",
            instance_name,
            region,
        )
        client = get_client("ec2", region)
        filters = [
            {
                "Name": "instance-state-name",
                "Values": ["pending", "running", "stopping", "stopped"],
            },
            {
                "Name": f"tag:{SPOT_OPERATOR_ID_TAG}",
                "Values": [instance_name],
            },
        ]

        paginator = client.get_paginator("describe_instances")

        page_iterator = paginator.paginate(Filters=filters)

        for page in page_iterator:
            for r in page.get("Reservations", []):
                if r.get("Instances"):
                    instances.extend(r["Instances"])
    except EndpointConnectionError as e:
        logger.debug(
            "Failed to list VMs for instance %s in region %s due to: %s",
            instance_name,
            region,
            e,
        )
        raise Exception("Failed to list VMs due to AWS connectivity problems")
    return instances


def extract_memory_mb_from_aws_pricing_memory_string(
    memory_string: str,
) -> int:
    if not memory_string:
        return 0
    matches = re.findall(r"^\s*(\d+)\s*(\w+)", memory_string)
    if matches:
        size = float(matches[0][0])
        unit = matches[0][1]
        if "G" in unit.upper():
            return int(size * 1024)
        elif "T" in unit.upper():
            return int(size * 1024 * 1024)
        else:
            return int(size)
    return 0


def get_all_instance_types_from_aws_regional_pricing_info(
    region: str, regional_pricing_info: dict
) -> list[InstanceTypeInfo]:
    instances: list[InstanceTypeInfo] = []

    for reg, reg_data in regional_pricing_info.get("regions", {}).items():
        for _, sku_data in reg_data.items():
            try:
                instances.append(
                    InstanceTypeInfo(
                        instance_type=sku_data["Instance Type"],
                        arch=infer_cpu_arch_from_aws_instance_type_name(
                            sku_data["Instance Type"]
                        ),
                        cloud=CLOUD_AWS,
                        region=region,
                        hourly_ondemand_price=float(sku_data["price"]),
                        monthly_ondemand_price=(
                            round(float(sku_data["price"]) * 24 * 30, 1)
                            if float(sku_data["price"]) * 24 * 30 < 100
                            else round(float(sku_data["price"]) * 24 * 30)
                        ),
                        cpu=int(sku_data["vCPU"]),
                        ram_mb=extract_memory_mb_from_aws_pricing_memory_string(
                            sku_data.get("Memory", "0")
                        ),
                        instance_storage=extract_instance_storage_size_and_type_from_aws_pricing_storage_string(
                            sku_data["Storage"]
                        )[
                            0
                        ],
                        storage_speed_class=extract_instance_storage_size_and_type_from_aws_pricing_storage_string(
                            sku_data["Storage"]
                        )[
                            1
                        ],
                        provider_description=sku_data,
                    )
                )
            except Exception as e:
                logger.error(
                    "Failed to parse instance info from: %s. Error: %s",
                    sku_data,
                    e,
                )

    return instances


def get_spot_instance_types_with_price_from_s3_pricing_json(
    region: str, spot_pricing_info: dict
) -> dict[str, float]:
    """Returns a dict of {instance_type: hourly_spot_price}
    Info extracted from: https://website.spot.ec2.aws.a2z.com/spot.json
    {
      "vers": 0.01,
      "config": {
        "rate": "perhr",
        "valueColumns": [
          "linux",
          "mswin"
        ],
        "currencies": [
          "USD"
        ],
        "regions": [
          {
            "region": "us-east-1",
            "footnotes": {
              "*": "notAvailableForCCorCGPU"
            },
            "instanceTypes": [
              {
                "type": "generalCurrentGen",
                "sizes": [
                  {
                    "size": "m6i.xlarge",
                    "valueColumns": [
                      {
                        "name": "linux",
                        "prices": {
                          "USD": "0.0615"
                        }
                      },
                      {
                        "name": "mswin",
                        "prices": {
                          "USD": "0.2032"
                        }
                      }
                    ]
                  },
    """
    ret = {}
    r = re.compile(r"[0-9.]")
    for rd in spot_pricing_info.get("config", {}).get("regions", []):
        if rd.get("region") != region:
            continue
        for ins_types in rd.get("instanceTypes", []):
            for size in ins_types.get("sizes", []):
                if not size.get("size"):
                    continue
                for vc in size.get("valueColumns", []):
                    if vc.get("name") == "linux":
                        if vc.get("prices", {}).get("USD", 0) and r.match(
                            vc.get("prices", {}).get("USD", 0)
                        ):
                            if float(vc.get("prices", {}).get("USD", 0)):
                                ret[size["size"]] = float(
                                    vc.get("prices", {}).get("USD", 0)
                                )

    return ret


def get_eviction_rate_brackets_from_public_eviction_info(
    public_eviction_rate_info: dict,
) -> dict:
    """Based on https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json
    eviction rate groups / brackets are defined by AWS as:
    [{'index': 0, 'label': '<5%', 'dots': 0, 'max': 5},
     {'index': 1, 'label': '5-10%', 'dots': 1, 'max': 11},
     {'index': 2, 'label': '10-15%', 'dots': 2, 'max': 16},
     {'index': 3, 'label': '15-20%', 'dots': 3, 'max': 22},
     {'index': 4, 'label': '>20%', 'dots': 4, 'max': 100}]
    """
    try:
        return {
            x["index"]: x for x in public_eviction_rate_info.get("ranges", [])
        }
    except Exception:
        logger.error("Failed to parse eviction rate groups")
    return {}


def extract_instance_type_eviction_rates_from_public_eviction_info(
    region: str, public_eviction_info: dict | None = None
) -> dict[str, EvictionRateInfo]:
    ret: dict[str, EvictionRateInfo] = {}

    if not public_eviction_info:
        public_eviction_info = get_spot_eviction_rates_from_public_json()
    if not public_eviction_info:
        raise Exception("Need eviction rate info to proceed")

    ev_brackets = get_eviction_rate_brackets_from_public_eviction_info(
        public_eviction_info
    )

    for instance_type, ev_info in (
        public_eviction_info.get("spot_advisor", {})
        .get(region, {})
        .get("Linux", {})
        .items()
    ):
        # In[156]: eviction_rate_info["spot_advisor"]["eu-north-1"]["Linux"]
        # Out[156]:
        # {'r5dn.24xlarge': {'s': 73, 'r': 2},
        #  'm7gd.8xlarge': {'s': 74, 'r': 1},

        try:
            ret[instance_type] = EvictionRateInfo(
                instance_type=instance_type,
                region=region,
                eviction_rate_group=ev_info["r"],
                eviction_rate_group_label=ev_brackets[ev_info["r"]]["label"],
                spot_savings_rate=ev_info["s"],
                eviction_rate_max_pct=ev_brackets[ev_info["r"]]["max"],
            )
        except Exception as e:
            logger.error(
                "Failed to parse instance eviction rate info from: %s. Error: %s",
                ev_info,
                e,
            )

    return ret


def add_eviction_rate_to_instance_types(
    region, instances: list[InstanceTypeInfo]
) -> list[InstanceTypeInfo]:
    ev_rate_info = (
        extract_instance_type_eviction_rates_from_public_eviction_info(region)
    )
    if not ev_rate_info:
        raise Exception(
            "Can't use eviction rate based selection as could not fetch eviction rate data"
        )
    for ins in instances:
        if ins.instance_type in ev_rate_info:
            ins.max_eviction_rate = ev_rate_info[
                ins.instance_type
            ].eviction_rate_max_pct
            ins.eviction_rate_group_label = ev_rate_info[
                ins.instance_type
            ].eviction_rate_group_label
    return instances
