from pg_spot_operator.cloud_impl.cloud_util import (
    extract_instance_storage_size_and_type_from_aws_pricing_storage_string,
)


def test_extract_instance_storage_size_and_type_from_aws_pricing_storage_string():
    test_strings = [
        ("125 GB NVMe SSD", (125, "nvme")),
        ("1 x 100 NVMe SSD", (100, "nvme")),
        ("2 x 1900 NVMe SSD", (3800, "nvme")),
        ("8 x 3840 GB SSD", (30720, "ssd")),
        ("10 sadasd", (10, "hdd")),
        ("EBS only", (0, "")),
    ]
    for ss, ret in test_strings:
        # print(ss, ret)
        assert (
            extract_instance_storage_size_and_type_from_aws_pricing_storage_string(
                ss
            )
            == ret
        )
