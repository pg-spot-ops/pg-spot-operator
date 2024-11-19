from pg_spot_operator.cloud_api import (
    boto3_api_instance_list_to_instance_type_info,
)
from tests.test_aws_spot import INSTANCE_LISTING


def test_boto3_api_instance_list_to_instance_type_info():

    iti = boto3_api_instance_list_to_instance_type_info(
        "eu-north-1", INSTANCE_LISTING
    )
    # for i in iti:
    #     print(i)
    assert iti
    assert len(iti) == len(INSTANCE_LISTING)
    as_dict = {x.instance_type: x for x in iti}
    assert "arm" in as_dict["r6gd.medium"].arch
    assert as_dict["r6gd.medium"].instance_storage > 10
    assert as_dict["r6gd.medium"].storage_speed_class == "ssd"
    assert as_dict["r6gd.medium"].ram_mb == 8192
    assert as_dict["r6gd.medium"].cpu == 1
