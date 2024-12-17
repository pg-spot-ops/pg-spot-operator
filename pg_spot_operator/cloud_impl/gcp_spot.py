# https://cloud.google.com/python/docs/reference/compute/latest
# https://github.com/GoogleCloudPlatform/python-docs-samples/tree/main/compute/client_library/snippets/instances
import logging
import os.path
import time
from dataclasses import dataclass

import google
import yaml
from google.cloud import compute_v1

from pg_spot_operator.cloud_impl.cloud_structs import InstanceTypeInfo
from pg_spot_operator.constants import CLOUD_GCP, CPU_ARCH_ARM, CPU_ARCH_X86
from pg_spot_operator.manifests import SectionVm
from pg_spot_operator.util import retrieve_url_to_local_text_file, timed_cache

GCP_PRICE_LIST_YAML_LOCAL_PATH = "~/.pg-spot-operator/gcp/pricing.yml"
GCP_PRICE_LIST_YAML_URL = "https://github.com/Cyclenerd/google-cloud-pricing-cost-calculator/raw/master/pricing.yml"

logger = logging.getLogger(__name__)

logging.getLogger("google").setLevel(logging.ERROR)


@dataclass
class GcpSkuWithPricing:
    sku: str
    region: str
    hourly_spot_price: float
    hourly_price: float
    cpu: int
    ram_gb: int


def get_yaml_price_list_refresh_if_needed(
    local_pricing_file_location: str,
) -> str:
    """Download new version max once per day (updated weekly)"""
    local_pricing_file_location = os.path.expanduser(
        local_pricing_file_location
    )
    if os.path.exists(local_pricing_file_location):
        fi = os.stat(local_pricing_file_location)
        if time.time() - fi.st_mtime > 3600 * 24:
            logger.debug(
                "Getting GCP VM pricelist from %s ...", GCP_PRICE_LIST_YAML_URL
            )
            return retrieve_url_to_local_text_file(
                GCP_PRICE_LIST_YAML_URL, local_pricing_file_location
            )
        else:  # Use cached version
            logger.debug(
                "Using cached GCP VM pricelist from %s",
                local_pricing_file_location,
            )
            with open(local_pricing_file_location, "r") as f:
                return f.read()
    else:
        logger.debug(
            "Getting GCP VM pricelist from %s ...", GCP_PRICE_LIST_YAML_URL
        )
        return retrieve_url_to_local_text_file(
            GCP_PRICE_LIST_YAML_URL, local_pricing_file_location
        )


def infer_cpu_arch_from_machine_name(
    machine_name: str,
) -> str:  # Re-validate the concept after a while
    if (
        machine_name.startswith("n2d")  # As of 2024-07-08
        or machine_name.startswith("t2d")
        or machine_name.startswith("t2a")
    ):
        return CPU_ARCH_ARM
    else:
        return CPU_ARCH_X86


def get_cheapest_spot_sku_for_hardware_requirements(
    max_skus_to_get: int,
    vm: SectionVm,
    region: str,
    skus_to_avoid: list[str] | None = None,
) -> list[InstanceTypeInfo]:
    pricing_data_yaml_input = get_yaml_price_list_refresh_if_needed(
        GCP_PRICE_LIST_YAML_LOCAL_PATH
    )
    all_spot_skus_pricing = parse_sku_pricing_from_yaml(
        pricing_data_yaml_input, region
    )
    hw_filtered_skus = (
        get_skus_matching_hardware_requirements_sorted_by_hourly_spot_price(
            all_spot_skus_pricing,
            cpu_min=vm.cpu_min,
            cpu_max=vm.cpu_max,
            ram_min=vm.ram_min,
            architecture=vm.architecture,
            storage_min=vm.storage_min,
            allow_burstable=vm.allow_burstable,
            storage_speed_class=vm.storage_speed_class,
            skus_to_avoid=skus_to_avoid,
        )
    )
    if not hw_filtered_skus:
        return []
    logger.debug(
        "SKUs in shortlist: %s",
        [(x.sku, x.hourly_spot_price) for x in hw_filtered_skus[:10]],
    )
    ret: list[InstanceTypeInfo] = []
    for s in hw_filtered_skus[:max_skus_to_get]:
        ret.append(
            InstanceTypeInfo(
                sku=s.sku,
                cloud=CLOUD_GCP,
                region=s.region,
                arch=infer_cpu_arch_from_machine_name(s.sku),
                monthly_spot_price=s.hourly_spot_price * 24 * 30,
                monthly_ondemand_price=s.hourly_price * 24 * 30,
                cpu=s.cpu,
                ram=s.ram_gb,
            )
        )
    logger.debug(
        "Cheapest SKU found - %s (%s) in GCP region %s for a monthly Spot price of $%s",
        ret[0].sku,
        ret[0].arch,
        ret[0].region,
        ret[0].monthly_spot_price,
    )
    return ret


def get_skus_matching_hardware_requirements_sorted_by_hourly_spot_price(
    skus_with_pricing_info: list[GcpSkuWithPricing],
    cpu_min: int | None = 0,
    cpu_max: int | None = 0,
    ram_min: int | None = 0,
    architecture: str | None = "any",
    storage_min: int | None = 0,
    allow_burstable: bool | None = False,
    storage_speed_class: str | None = "any",
    skus_to_avoid: list[str] | None = None,
) -> list[GcpSkuWithPricing]:
    ret: list[GcpSkuWithPricing] = []
    for sku in skus_with_pricing_info:
        if skus_to_avoid and sku.sku in skus_to_avoid:
            continue
        if cpu_min and cpu_min > sku.cpu:
            continue
        if cpu_max and sku.cpu > cpu_max:
            continue
        if ram_min and ram_min > sku.ram_gb:
            continue
        if architecture and (
            "arm" in architecture
            and not (
                sku.sku.startswith("t2a")
                or sku.sku.startswith("t2d")
                or sku.sku.startswith("n2d")
            )
        ):
            continue
        if storage_min:  # TODO account for actually available storage
            # https://cloud.google.com/compute/docs/machine-resource#lssd-types
            # gcloud compute machine-types describe c3d-standard-8-lssd --zone europe-west4-a
            # creationTimestamp: '1969-12-31T16:00:00.000-08:00'
            # description: 8 vCPUs, 32 GB RAM, 1 local SSD
            if not (
                sku.sku.endswith("-lssd")
                or (sku.sku.startswith("n2") or sku.sku.startswith("n1"))
            ):
                continue
        ret.append(sku)
    ret.sort(key=lambda x: x.hourly_spot_price)
    return ret


def parse_sku_pricing_from_yaml(
    pricing_yaml_contents: str,
    region: str | None = None,
    spot_only: bool = True,
) -> list[GcpSkuWithPricing]:
    """https://github.com/Cyclenerd/google-cloud-pricing-cost-calculator?tab=readme-ov-file#2-download-price-information
    ---
    about:
    compute:
      instance:
        a2-highgpu-1g:
        cost:
        africa-south1:
          hour: 4.80478794
          hour_spot: 1.441435835
    """
    ret: list[GcpSkuWithPricing] = []
    pricing_info = yaml.safe_load(pricing_yaml_contents)
    for sku_name, sku_data in pricing_info["compute"]["instance"].items():
        for ci_reg, ci in sku_data["cost"].items():
            if region and region != ci_reg:
                continue
            if spot_only and "hour_spot" not in ci:
                continue
            if ci.get("hour") == 0:
                continue  # SKU not available in region
            ret.append(
                GcpSkuWithPricing(
                    sku=sku_name,
                    cpu=sku_data["cpu"],
                    ram_gb=sku_data["ram"],
                    region=ci_reg,
                    hourly_spot_price=ci["hour_spot"],
                    hourly_price=ci["hour"],
                )
            )

    return ret


def describe_machine_type(
    gcp_project_id: str, az: str, machine_type: str
) -> dict:
    """API call returns https://cloud.google.com/python/docs/reference/compute/latest/google.cloud.compute_v1.types.MachineType
    but convert to dict for unification purposes.

    Sample API response:

    creation_timestamp: "1969-12-31T16:00:00.000-08:00"
    description: "Efficient Instance, 2 vCPUs, 2 GB RAM"
    guest_cpus: 2
    id: 337002
    image_space_gb: 0
    is_shared_cpu: false
    kind: "compute#machineType"
    maximum_persistent_disks: 128
    maximum_persistent_disks_size_gb: 263168
    memory_mb: 2048
    name: "e2-highcpu-2"
    self_link: "https://www.googleapis.com/compute/v1/projects/kaarel-devel/zones/europe-north1-b/machineTypes/e2-highcpu-2"
    zone: "europe-north1-b"
    """
    logger.debug(
        "Describing GCP machine_type %s project %s AZ %s ...",
        machine_type,
        gcp_project_id,
        az,
    )
    client = compute_v1.MachineTypesClient()

    # The native class doesn't support __dict__ so need to convert manually :(
    i = client.get(project=gcp_project_id, zone=az, machine_type=machine_type)
    if i:
        return {
            "description": i.description,
            "guest_cpus": i.guest_cpus,
            "image_space_gb": i.image_space_gb,
            "is_shared_cpu": i.is_shared_cpu,
            "maximum_persistent_disks": i.maximum_persistent_disks,
            "maximum_persistent_disks_size_gb": i.maximum_persistent_disks_size_gb,
            "memory_mb": i.memory_mb,
            "name": i.name,
            "zone": i.zone,
        }
    return {}


def get_current_hourly_spot_price(
    region: str,
    instance_type: str,
    pricing_data: list[GcpSkuWithPricing] | None = None,
) -> float:
    if not pricing_data:
        pricing_data_yaml_input = get_yaml_price_list_refresh_if_needed(
            GCP_PRICE_LIST_YAML_LOCAL_PATH
        )
        pricing_data = parse_sku_pricing_from_yaml(
            pricing_data_yaml_input, region
        )
    for pd in pricing_data:
        if pd.sku == instance_type and pd.region == region:
            return pd.hourly_spot_price
    return 0


def get_current_hourly_ondemand_price(
    region: str,
    instance_type: str,
    pricing_data: list[GcpSkuWithPricing] | None = None,
) -> float:
    if not pricing_data:
        pricing_data_yaml_input = get_yaml_price_list_refresh_if_needed(
            GCP_PRICE_LIST_YAML_LOCAL_PATH
        )
        pricing_data = parse_sku_pricing_from_yaml(
            pricing_data_yaml_input, region
        )
    for pd in pricing_data:
        if pd.sku == instance_type and pd.region == region:
            return pd.hourly_price
    return 0


@timed_cache(seconds=30)
def get_all_running_operator_instances_for_project_in_az(
    gcp_project_id: str, az: str
) -> list[google.cloud.compute_v1.types.compute.Instance]:
    logger.debug(
        "Scanning for running operator managed GCP VMs from project %s in zone %s ...",
        gcp_project_id,
        az,
    )
    client = compute_v1.InstancesClient()
    instances = list(client.list(project=gcp_project_id, zone=az))
    logger.debug("A total of %s operator tagged VMs found", len(instances))
    return instances
