import logging
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean

import requests

from pg_spot_operator.cloud_impl.aws_client import get_client
from pg_spot_operator.cloud_impl.cloud_structs import ResolvedInstanceTypeInfo
from pg_spot_operator.cloud_impl.cloud_util import (
    extract_cpu_arch_from_sku_desc,
)
from pg_spot_operator.constants import (
    CLOUD_AWS,
    MF_SEC_VM_STORAGE_TYPE_LOCAL,
    SPOT_OPERATOR_ID_TAG,
)
from pg_spot_operator.instance_type import InstanceType
from pg_spot_operator.util import timed_cache

MAX_SKUS_FOR_SPOT_PRICE_COMPARE = 10
SPOT_HISTORY_LOOKBACK_DAYS = 1


logger = logging.getLogger(__name__)
# Reduce boto noisiness https://github.com/boto/boto3/issues/521#issuecomment-653060090
logging.getLogger("boto3").setLevel(logging.ERROR)
logging.getLogger("botocore").setLevel(logging.ERROR)
logging.getLogger("nose").setLevel(logging.ERROR)
logging.getLogger("s3transfer").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)


@timed_cache(seconds=3600)
def describe_instance_type(instance_type: str, region: str) -> dict:
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


def resolve_instance_type_info(
    instance_type: str, region: str, i_desc: dict | None = None
) -> ResolvedInstanceTypeInfo:
    """i_desc = AWS API response dict. e.g.: aws ec2 describe-instance-types --instance-types i3en.xlarge"""
    if not i_desc:
        i_desc = describe_instance_type(instance_type, region)
    if not i_desc:
        raise Exception(
            f"Could not describe instance type {instance_type} in region {region}"
        )
    return ResolvedInstanceTypeInfo(
        instance_type=instance_type,
        arch=extract_cpu_arch_from_sku_desc(CLOUD_AWS, i_desc),
        cloud=CLOUD_AWS,
        region=region,
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

    return instances


# TODO some caching
def get_current_hourly_spot_price(
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


def get_current_hourly_ondemand_price(
    region: str,
    instance_type: str,
) -> float:
    """Uses an external service for now"""
    URL = f"https://ec2.shop/?region={region}&filter={instance_type}"
    f = requests.get(
        URL, headers={"Content-Type": "application/json"}, timeout=5
    )
    if f.status_code != 200:
        return 0
    pd = f.json()
    if not pd["Prices"]:
        return 0
    return round(pd["Prices"][0]["Cost"], 6)


def filter_instance_types_by_hw_req(
    instance_types: list[dict],
    cpu_min: int | None = 0,
    cpu_max: int | None = 0,
    ram_min: int | None = 0,
    architecture: str | None = "any",
    storage_min: int | None = 0,
    storage_type: str = "network",
    allow_burstable: bool = True,
    storage_speed_class: str | None = "any",
    instance_types_to_avoid: list[str] | None = None,
) -> list[dict]:
    """Returns qualified SKUs sorted by (CPU, RAM) or (CPU, Total instance storage DESC)"""
    ret = []
    for i in instance_types:
        if (
            instance_types_to_avoid
            and i["InstanceType"] in instance_types_to_avoid
        ):
            continue

        if architecture and architecture != "any":
            if architecture not in ",".join(
                i["ProcessorInfo"]["SupportedArchitectures"]
            ):
                # On AWS architectures are named x86_64 and arm64
                continue

        if allow_burstable is False and i["BurstablePerformanceSupported"]:
            continue

        if cpu_min:
            cpus = i["VCpuInfo"]["DefaultVCpus"]
            if cpus < cpu_min:
                continue

        if cpu_max:
            cpus = i["VCpuInfo"]["DefaultVCpus"]
            if cpus > cpu_max:
                continue

        if ram_min:
            ram_mb = i["MemoryInfo"]["SizeInMiB"]
            if ram_mb < ram_min * 1000:
                continue
        if storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL and not i.get(
            "InstanceStorageSupported"
        ):
            continue
        if storage_min and storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL:
            if i["InstanceStorageInfo"]["TotalSizeInGB"] < storage_min:
                continue
            instance_storage_speed_class = i["InstanceStorageInfo"]["Disks"][
                0
            ]["Type"]
            if (
                storage_speed_class == "hdd"
                and instance_storage_speed_class != "hdd"
            ):  # Consider SSD to be equal with NVME for AWS
                continue
        ret.append(i)
    if storage_min and storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL:
        ret.sort(
            key=lambda x: (
                x["VCpuInfo"]["DefaultVCpus"],
                x["InstanceStorageInfo"]["TotalSizeInGB"],
            )
        )
    else:
        ret.sort(
            key=lambda x: (
                x["VCpuInfo"]["DefaultVCpus"],
                x["MemoryInfo"]["SizeInMiB"],
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
    """Returns SKUs by region and price, cheapest first"""

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


def get_cheapest_sku_for_hw_reqs(
    max_skus_to_get: int,
    region: str,
    availability_zone: str | None = None,
    cpu_min: int = 0,
    cpu_max: int = 0,
    ram_min: int = 0,
    architecture: str = "any",
    storage_type: str = "network",
    storage_min: int = 0,
    allow_burstable: bool = True,
    storage_speed_class: str = "any",
    instance_types_to_avoid: list[str] | None = None,
    instance_selection_strategy: str | None = None,
) -> list[ResolvedInstanceTypeInfo]:
    """Returns a price-sorted list"""

    all_instances_for_region = get_all_ec2_spot_instance_types(
        region,
        with_local_storage_only=(storage_type == MF_SEC_VM_STORAGE_TYPE_LOCAL),
    )
    logger.debug(
        "%s total instance types found for region %s",
        len(all_instances_for_region),
        region,
    )
    filtered_instances = filter_instance_types_by_hw_req(
        all_instances_for_region,
        cpu_min=cpu_min,
        cpu_max=cpu_max,
        ram_min=ram_min,
        architecture=architecture,
        storage_min=storage_min,
        storage_type=storage_type,
        allow_burstable=allow_burstable,
        storage_speed_class=storage_speed_class,
        instance_types_to_avoid=instance_types_to_avoid,
    )

    logger.debug("%s of them matching min HW reqs", len(filtered_instances))

    if len(filtered_instances) > MAX_SKUS_FOR_SPOT_PRICE_COMPARE:
        logger.debug(
            "Reducing to %s instance types by CPU count to reduce pricing history fetching",
            MAX_SKUS_FOR_SPOT_PRICE_COMPARE,
        )
        filtered_instances = filtered_instances[
            :MAX_SKUS_FOR_SPOT_PRICE_COMPARE
        ]

    filtered_instance_types = [x["InstanceType"] for x in filtered_instances]
    hourly_pricing_data = get_spot_pricing_data_for_skus_over_period(
        filtered_instance_types,
        region,
        timedelta(days=SPOT_HISTORY_LOOKBACK_DAYS),
        availability_zone,
    )
    if not hourly_pricing_data:
        raise Exception(
            "Could not fetch pricing data, can't select SKU"
        )  # TODO use last cached data
    avg_by_sku_az = get_avg_spot_price_from_pricing_history_data_by_sku_and_az(
        hourly_pricing_data
    )

    instance_selection_strategy_cls = InstanceType.get_selection_strategy(
        instance_selection_strategy
    )
    logger.debug(
        "Applying instance selection strategy: %s ...",
        instance_selection_strategy,
    )
    sku, az, price = instance_selection_strategy_cls.execute(avg_by_sku_az)

    arch: str = ""
    i_desc: dict = {}
    for i in filtered_instances:
        if i["InstanceType"] == sku:
            i_desc = i
            arch = extract_cpu_arch_from_sku_desc(CLOUD_AWS, i)
    if not i_desc or not arch:
        Exception("Should not happen")

    monthly_price = round(price * 24 * 30, 1)
    logger.debug(
        "Cheapest SKU found - %s (%s) in AWS zone %s a for monthly Spot price of $%s",
        sku,
        arch,
        az,
        round(price * 24 * 30, 1),
    )
    logger.debug(
        "Instance types in selection: %s", {x[0] for x in avg_by_sku_az}
    )
    logger.debug("Prices in selection: %s", avg_by_sku_az)

    # TODO respect max_skus
    return [
        ResolvedInstanceTypeInfo(
            instance_type=sku,
            cloud=CLOUD_AWS,
            region=region,
            arch=arch,
            provider_description=i_desc,
            monthly_spot_price=monthly_price,
            availability_zone=az,
            cpu=i_desc.get("VCpuInfo", {}).get("DefaultVCpus", 0),
            ram_mb=i_desc.get("MemoryInfo", {}).get("SizeInMiB", 0),
            instance_storage=i_desc.get("InstanceStorageInfo", {}).get(
                "TotalSizeInGB", 0
            ),
        )
    ]


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


@timed_cache(seconds=10)
def get_backing_vms_for_instances_if_any(
    region: str, instance_name: str
) -> list[dict]:
    instances = []
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
    return instances
