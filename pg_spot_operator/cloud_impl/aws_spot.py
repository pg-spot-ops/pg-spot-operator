import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean

import requests
from botocore.exceptions import EndpointConnectionError

from pg_spot_operator.cloud_impl.aws_cache import (
    get_aws_static_ondemand_pricing_info,
)
from pg_spot_operator.cloud_impl.aws_client import get_client
from pg_spot_operator.cloud_impl.cloud_structs import InstanceTypeInfo
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
) -> InstanceTypeInfo:
    """i_desc = AWS API response dict. e.g.: aws ec2 describe-instance-types --instance-types i3en.xlarge"""
    if not i_desc:
        i_desc = describe_instance_type(instance_type, region)
    if not i_desc:
        raise Exception(
            f"Could not describe instance type {instance_type} in region {region}"
        )
    return InstanceTypeInfo(
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

    logger.debug(
        "%s total instance types found for region %s via describe_instance_types. with_local_storage_only=%s",
        len(instances),
        region,
        with_local_storage_only,
    )
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
    instance_types: list[InstanceTypeInfo],
    cpu_min: int | None = 0,
    cpu_max: int | None = 0,
    ram_min: int | None = 0,
    architecture: str | None = "any",
    storage_min: int | None = 0,
    storage_type: str = "network",
    allow_burstable: bool = True,
    storage_speed_class: str | None = "any",
    instance_types_to_avoid: list[str] | None = None,
) -> list[InstanceTypeInfo]:
    """Returns qualified SKUs sorted by (CPU, RAM) or (CPU, Total instance storage DESC)"""
    ret: list[InstanceTypeInfo] = []
    for ii in instance_types:
        if (
            instance_types_to_avoid
            and ii.instance_type in instance_types_to_avoid
        ):
            continue

        if architecture and architecture.strip() and architecture != "any":
            if (
                architecture.strip() not in ii.arch
            ):  # On AWS architectures are named x86_64 and arm64
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


def get_cheapest_sku_for_hw_reqs(
    all_instances: list[InstanceTypeInfo],
    region: str,
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
    instance_types_to_avoid: list[str] | None = None,
    instance_selection_strategy: str | None = None,
) -> list[InstanceTypeInfo]:
    """Returns a price-sorted list"""
    if not all_instances:
        raise Exception("Need all_instances to select cheapest")

    logger.debug(
        "Filtering through %s instances types to mathc HW reqs ...",
        len(all_instances),
    )
    filtered_instances_by_cpu = filter_instance_types_by_hw_req(
        all_instances,
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

    logger.debug(
        "%s of them matching min HW reqs", len(filtered_instances_by_cpu)
    )

    if len(filtered_instances_by_cpu) > MAX_SKUS_FOR_SPOT_PRICE_COMPARE:
        logger.debug(
            "Reducing to %s instance types by CPU count to reduce pricing history fetching",
            MAX_SKUS_FOR_SPOT_PRICE_COMPARE,
        )
        filtered_instances_by_cpu = filtered_instances_by_cpu[
            :MAX_SKUS_FOR_SPOT_PRICE_COMPARE
        ]

    filtered_instance_types = [
        x.instance_type for x in filtered_instances_by_cpu
    ]
    avg_by_sku_az: list[tuple[str, str, float]] = (
        []
    )  # [(i3.xlarge, eu-north-1, 0.0132),]

    if use_boto3:
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
        avg_by_sku_az = (
            get_avg_spot_price_from_pricing_history_data_by_sku_and_az(
                hourly_pricing_data
            )
        )
    else:
        avg_by_sku_az = get_filtered_instances_by_price_no_az(
            filtered_instances_by_cpu
        )

    instance_selection_strategy_cls = InstanceType.get_selection_strategy(
        instance_selection_strategy
    )
    logger.debug(
        "Applying instance selection strategy: %s ...",
        instance_selection_strategy,
    )
    selected_instance_type, az, price = (
        instance_selection_strategy_cls.execute(avg_by_sku_az)
    )

    iti: InstanceTypeInfo | None = None
    for i in filtered_instances_by_cpu:
        if i.instance_type == selected_instance_type:
            iti = i
    if not iti:
        raise Exception("Should not happen")

    if az:
        iti.availability_zone = az
    if not iti.monthly_spot_price:
        iti.monthly_spot_price = round(price * 24 * 30, 1)

    logger.debug(
        "Cheapest SKU found - %s (%s) in AWS zone %s a for monthly Spot price of $%s",
        selected_instance_type,
        iti.arch,
        az,
        round(price * 24 * 30, 1),
    )
    logger.debug("Instances / Prices in selection: %s", avg_by_sku_az)

    # TODO respect max_skus
    return [iti]


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
                        monthly_ondemand_price=float(sku_data["price"])
                        * 24
                        * 30,
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
) -> dict:
    """Info from: https://website.spot.ec2.aws.a2z.com/spot.json
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

    for rd in spot_pricing_info.get("config", {}).get("regions", []):
        if rd.get("region") != region:
            continue
        for ins_types in rd.get("instanceTypes", []):
            for size in ins_types.get("sizes", []):
                if not size.get("size"):
                    continue
                for vc in size.get("valueColumns", []):
                    if vc.get("name") == "linux":
                        ret[size["size"]] = float(
                            vc.get("prices", {}).get("USD", 0)
                        )

    return ret
