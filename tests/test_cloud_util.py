import pytest

from pg_spot_operator.cloud_impl.cloud_util import (
    extract_instance_storage_size_and_type_from_aws_pricing_storage_string,
    is_explicit_aws_region_code,
    extract_instance_family_from_instance_type_code,
    infer_cpu_arch_from_aws_instance_type_name, network_volume_nr_to_device_name,
)
from pg_spot_operator.constants import CPU_ARCH_ARM, CPU_ARCH_X86


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


def test_is_explicit_aws_region_code():
    assert is_explicit_aws_region_code("eu-north-1")
    assert not is_explicit_aws_region_code("")
    assert not is_explicit_aws_region_code("eu-")
    assert not is_explicit_aws_region_code("paris|stock")
    assert not is_explicit_aws_region_code("eu-(ce|no)")


def test_extract_instance_type_family():
    assert (
        extract_instance_family_from_instance_type_code("i4g.2xlarge") == "i4g"
    )
    assert (
        extract_instance_family_from_instance_type_code("u-24tb1.112xlarge")
        == "u-24tb1"
    )
    with pytest.raises(Exception):
        extract_instance_family_from_instance_type_code("2xlarge")


def test_infer_cpu_arch_from_aws_instance_type_name():
    assert (
        infer_cpu_arch_from_aws_instance_type_name("g4dn.xlarge")
        == CPU_ARCH_X86
    )
    assert (
        infer_cpu_arch_from_aws_instance_type_name("c6g.large") == CPU_ARCH_ARM
    )


def test_network_volume_nr_to_device_name():
    assert network_volume_nr_to_device_name(2) == "/dev/sdd"
