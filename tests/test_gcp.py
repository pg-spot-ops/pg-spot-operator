import unittest

from pg_spot_operator.cloud_impl.gcp_spot import (
    parse_sku_pricing_from_yaml,
    describe_machine_type,
    get_skus_matching_hardware_requirements_sorted_by_hourly_spot_price,
    get_current_hourly_spot_price,
    get_all_running_operator_instances_for_project_in_az,
)
from pg_spot_operator.util import (
    gcp_get_default_project_id_and_zone_from_local_config_if_set,
)

SAMPLE_GCP_PRICING_DATA_YAML = """
# https://github.com/Cyclenerd/google-cloud-pricing-cost-calculator
---
about:
compute:
  instance:
    t2a-standard-1:
      cost:
        africa-south1:
          hour: 0
          month: 0
          month_1y: 0
          month_3y: 0
        europe-west4:
          hour: 0.04044409
          hour_spot: 0.012711
          month: 29.5241857
          month_1y: 29.5241857
          month_3y: 29.5241857
          month_spot: 9.27903
      cpu: 1
      ram: 4
    e2-highcpu-2:
      cost:
        africa-south1:
          hour: 0.064707074
          hour_spot: 0.022318
          month: 47.23616402
          month_1y: 29.75877996
          month_3y: 21.2562714
          month_spot: 16.29214
        us-west4:
          hour: 0.05571888
          hour_spot: 0.007056
          month: 40.6747824
          month_1y: 25.62511116
          month_3y: 18.30365062
          month_spot: 5.15088
      cpu: 2
      ram: 2
"""


def test_filter_instance_types_by_hw_req():
    all_skus = parse_sku_pricing_from_yaml(SAMPLE_GCP_PRICING_DATA_YAML)
    # print(all_skus)
    assert len(all_skus) == 3
    all_skus_reg = parse_sku_pricing_from_yaml(
        SAMPLE_GCP_PRICING_DATA_YAML, region="europe-west4"
    )
    assert len(all_skus_reg) == 1
    filtered = (
        get_skus_matching_hardware_requirements_sorted_by_hourly_spot_price(
            all_skus, skus_to_avoid=["e2-highcpu-2"]
        )
    )
    assert len(filtered) == 1


def test_describe_machine_type_via_gcp_api():
    sku = "e2-highcpu-2"
    def_project_id, def_zone = (
        gcp_get_default_project_id_and_zone_from_local_config_if_set()
    )
    if not def_project_id:
        return

    desc = describe_machine_type(
        gcp_project_id=def_project_id,
        az=def_zone,
        machine_type=sku,
    )
    assert desc["guest_cpus"] == 2


def test_get_current_spot_price():
    pd = parse_sku_pricing_from_yaml(SAMPLE_GCP_PRICING_DATA_YAML)
    # print(pd)
    sp = get_current_hourly_spot_price(
        "us-west4", "e2-highcpu-2", pricing_data=pd
    )
    # print(sp)
    assert 0.007 < sp < 0.008


@unittest.SkipTest
def test_get_all_running_operator_instances_for_project_in_az():
    def_project_id, def_zone = (
        gcp_get_default_project_id_and_zone_from_local_config_if_set()
    )
    if not def_project_id:
        return
    print("GCP VMs in", def_project_id, def_zone)
    print(
        len(
            get_all_running_operator_instances_for_project_in_az(
                def_project_id, def_zone
            )
        )
    )
