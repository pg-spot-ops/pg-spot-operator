import datetime
import unittest

from dateutil.tz import tzutc

from pg_spot_operator.cloud_api import (
    boto3_api_instance_list_to_instance_type_info,
)
from pg_spot_operator.cloud_impl import aws_spot
from pg_spot_operator.cloud_impl.aws_spot import (
    get_current_hourly_spot_price_boto3,
    get_current_hourly_ondemand_price,
    filter_instance_types_by_hw_req,
    resolve_instance_type_info,
    get_ondemand_price_for_instance_type_from_aws_regional_pricing_info,
    get_spot_instance_types_with_price_from_s3_pricing_json,
    extract_memory_mb_from_aws_pricing_memory_string,
    get_all_instance_types_from_aws_regional_pricing_info,
    get_eviction_rate_brackets_from_public_eviction_info,
    extract_instance_type_eviction_rates_from_public_eviction_info,
)
from pg_spot_operator.constants import (
    MF_SEC_VM_STORAGE_TYPE_LOCAL,
    CPU_ARCH_X86,
)

INSTANCE_LISTING = [
    {
        "InstanceType": "r6gd.medium",
        "CurrentGeneration": True,
        "FreeTierEligible": False,
        "SupportedUsageClasses": ["on-demand", "spot"],
        "SupportedRootDeviceTypes": ["ebs"],
        "SupportedVirtualizationTypes": ["hvm"],
        "BareMetal": False,
        "Hypervisor": "nitro",
        "ProcessorInfo": {
            "SupportedArchitectures": ["arm64"],
            "SustainedClockSpeedInGhz": 2.5,
            "Manufacturer": "AWS",
        },
        "VCpuInfo": {
            "DefaultVCpus": 1,
            "DefaultCores": 1,
            "DefaultThreadsPerCore": 1,
        },
        "MemoryInfo": {"SizeInMiB": 8192},
        "InstanceStorageSupported": True,
        "InstanceStorageInfo": {
            "TotalSizeInGB": 59,
            "Disks": [{"SizeInGB": 59, "Count": 1, "Type": "ssd"}],
            "NvmeSupport": "required",
            "EncryptionSupport": "required",
        },
        "EbsInfo": {
            "EbsOptimizedSupport": "default",
            "EncryptionSupport": "supported",
            "EbsOptimizedInfo": {
                "BaselineBandwidthInMbps": 315,
                "BaselineThroughputInMBps": 39.375,
                "BaselineIops": 2500,
                "MaximumBandwidthInMbps": 4750,
                "MaximumThroughputInMBps": 593.75,
                "MaximumIops": 20000,
            },
            "NvmeSupport": "required",
        },
        "NetworkInfo": {
            "NetworkPerformance": "Up to 10 Gigabit",
            "MaximumNetworkInterfaces": 2,
            "MaximumNetworkCards": 1,
            "DefaultNetworkCardIndex": 0,
            "NetworkCards": [
                {
                    "NetworkCardIndex": 0,
                    "NetworkPerformance": "Up to 10 Gigabit",
                    "MaximumNetworkInterfaces": 2,
                    "BaselineBandwidthInGbps": 0.5,
                    "PeakBandwidthInGbps": 10.0,
                }
            ],
            "Ipv4AddressesPerInterface": 4,
            "Ipv6AddressesPerInterface": 4,
            "Ipv6Supported": True,
            "EnaSupport": "required",
            "EfaSupported": False,
            "EncryptionInTransitSupported": False,
            "EnaSrdSupported": False,
        },
        "PlacementGroupInfo": {
            "SupportedStrategies": ["cluster", "partition", "spread"]
        },
        "HibernationSupported": True,
        "BurstablePerformanceSupported": False,
        "DedicatedHostsSupported": True,
        "AutoRecoverySupported": False,
        "SupportedBootModes": ["uefi"],
        "NitroEnclavesSupport": "unsupported",
        "NitroTpmSupport": "supported",
        "NitroTpmInfo": {"SupportedVersions": ["2.0"]},
        "PhcSupport": "unsupported",
    },
    {
        "InstanceType": "c7a.medium",
        "CurrentGeneration": True,
        "FreeTierEligible": False,
        "SupportedUsageClasses": ["on-demand", "spot"],
        "SupportedRootDeviceTypes": ["ebs"],
        "SupportedVirtualizationTypes": ["hvm"],
        "BareMetal": False,
        "Hypervisor": "nitro",
        "ProcessorInfo": {
            "SupportedArchitectures": ["x86_64"],
            "SustainedClockSpeedInGhz": 3.7,
            "Manufacturer": "AMD",
        },
        "VCpuInfo": {
            "DefaultVCpus": 1,
            "DefaultCores": 1,
            "DefaultThreadsPerCore": 1,
        },
        "MemoryInfo": {"SizeInMiB": 2048},
        "InstanceStorageSupported": False,
        "EbsInfo": {
            "EbsOptimizedSupport": "default",
            "EncryptionSupport": "supported",
            "EbsOptimizedInfo": {
                "BaselineBandwidthInMbps": 325,
                "BaselineThroughputInMBps": 40.625,
                "BaselineIops": 2500,
                "MaximumBandwidthInMbps": 10000,
                "MaximumThroughputInMBps": 1250.0,
                "MaximumIops": 40000,
            },
            "NvmeSupport": "required",
        },
        "NetworkInfo": {
            "NetworkPerformance": "Up to 12.5 Gigabit",
            "MaximumNetworkInterfaces": 2,
            "MaximumNetworkCards": 1,
            "DefaultNetworkCardIndex": 0,
            "NetworkCards": [
                {
                    "NetworkCardIndex": 0,
                    "NetworkPerformance": "Up to 12.5 Gigabit",
                    "MaximumNetworkInterfaces": 2,
                    "BaselineBandwidthInGbps": 0.39,
                    "PeakBandwidthInGbps": 12.5,
                }
            ],
            "Ipv4AddressesPerInterface": 4,
            "Ipv6AddressesPerInterface": 4,
            "Ipv6Supported": True,
            "EnaSupport": "required",
            "EfaSupported": False,
            "EncryptionInTransitSupported": True,
            "EnaSrdSupported": False,
        },
        "PlacementGroupInfo": {
            "SupportedStrategies": ["cluster", "partition", "spread"]
        },
        "HibernationSupported": False,
        "BurstablePerformanceSupported": False,
        "DedicatedHostsSupported": True,
        "AutoRecoverySupported": True,
        "SupportedBootModes": ["legacy-bios", "uefi"],
        "NitroEnclavesSupport": "unsupported",
        "NitroTpmSupport": "supported",
        "NitroTpmInfo": {"SupportedVersions": ["2.0"]},
        "PhcSupport": "unsupported",
    },
    {
        "InstanceType": "m6gd.medium",
        "CurrentGeneration": True,
        "FreeTierEligible": False,
        "SupportedUsageClasses": ["on-demand", "spot"],
        "SupportedRootDeviceTypes": ["ebs"],
        "SupportedVirtualizationTypes": ["hvm"],
        "BareMetal": False,
        "Hypervisor": "nitro",
        "ProcessorInfo": {
            "SupportedArchitectures": ["arm64"],
            "SustainedClockSpeedInGhz": 2.5,
            "Manufacturer": "AWS",
        },
        "VCpuInfo": {
            "DefaultVCpus": 1,
            "DefaultCores": 1,
            "DefaultThreadsPerCore": 1,
        },
        "MemoryInfo": {"SizeInMiB": 4096},
        "InstanceStorageSupported": True,
        "InstanceStorageInfo": {
            "TotalSizeInGB": 59,
            "Disks": [{"SizeInGB": 59, "Count": 1, "Type": "ssd"}],
            "NvmeSupport": "required",
            "EncryptionSupport": "required",
        },
        "EbsInfo": {
            "EbsOptimizedSupport": "default",
            "EncryptionSupport": "supported",
            "EbsOptimizedInfo": {
                "BaselineBandwidthInMbps": 315,
                "BaselineThroughputInMBps": 39.375,
                "BaselineIops": 2500,
                "MaximumBandwidthInMbps": 4750,
                "MaximumThroughputInMBps": 593.75,
                "MaximumIops": 20000,
            },
            "NvmeSupport": "required",
        },
        "NetworkInfo": {
            "NetworkPerformance": "Up to 10 Gigabit",
            "MaximumNetworkInterfaces": 2,
            "MaximumNetworkCards": 1,
            "DefaultNetworkCardIndex": 0,
            "NetworkCards": [
                {
                    "NetworkCardIndex": 0,
                    "NetworkPerformance": "Up to 10 Gigabit",
                    "MaximumNetworkInterfaces": 2,
                    "BaselineBandwidthInGbps": 0.5,
                    "PeakBandwidthInGbps": 10.0,
                }
            ],
            "Ipv4AddressesPerInterface": 4,
            "Ipv6AddressesPerInterface": 4,
            "Ipv6Supported": True,
            "EnaSupport": "required",
            "EfaSupported": False,
            "EncryptionInTransitSupported": False,
            "EnaSrdSupported": False,
        },
        "PlacementGroupInfo": {
            "SupportedStrategies": ["cluster", "partition", "spread"]
        },
        "HibernationSupported": True,
        "BurstablePerformanceSupported": False,
        "DedicatedHostsSupported": True,
        "AutoRecoverySupported": False,
        "SupportedBootModes": ["uefi"],
        "NitroEnclavesSupport": "unsupported",
        "NitroTpmSupport": "supported",
        "NitroTpmInfo": {"SupportedVersions": ["2.0"]},
        "PhcSupport": "unsupported",
    },
    {
        "InstanceType": "t4g.medium",
        "CurrentGeneration": True,
        "FreeTierEligible": False,
        "SupportedUsageClasses": ["on-demand", "spot"],
        "SupportedRootDeviceTypes": ["ebs"],
        "SupportedVirtualizationTypes": ["hvm"],
        "BareMetal": False,
        "Hypervisor": "nitro",
        "ProcessorInfo": {
            "SupportedArchitectures": ["arm64"],
            "SustainedClockSpeedInGhz": 2.5,
            "Manufacturer": "AWS",
        },
        "VCpuInfo": {
            "DefaultVCpus": 2,
            "DefaultCores": 2,
            "DefaultThreadsPerCore": 1,
            "ValidCores": [1, 2],
            "ValidThreadsPerCore": [1],
        },
        "MemoryInfo": {"SizeInMiB": 4096},
        "InstanceStorageSupported": False,
        "EbsInfo": {
            "EbsOptimizedSupport": "default",
            "EncryptionSupport": "supported",
            "EbsOptimizedInfo": {
                "BaselineBandwidthInMbps": 347,
                "BaselineThroughputInMBps": 43.375,
                "BaselineIops": 2000,
                "MaximumBandwidthInMbps": 2085,
                "MaximumThroughputInMBps": 260.625,
                "MaximumIops": 11800,
            },
            "NvmeSupport": "required",
        },
        "NetworkInfo": {
            "NetworkPerformance": "Up to 5 Gigabit",
            "MaximumNetworkInterfaces": 3,
            "MaximumNetworkCards": 1,
            "DefaultNetworkCardIndex": 0,
            "NetworkCards": [
                {
                    "NetworkCardIndex": 0,
                    "NetworkPerformance": "Up to 5 Gigabit",
                    "MaximumNetworkInterfaces": 3,
                    "BaselineBandwidthInGbps": 0.256,
                    "PeakBandwidthInGbps": 5.0,
                }
            ],
            "Ipv4AddressesPerInterface": 6,
            "Ipv6AddressesPerInterface": 6,
            "Ipv6Supported": True,
            "EnaSupport": "required",
            "EfaSupported": False,
            "EncryptionInTransitSupported": False,
            "EnaSrdSupported": False,
        },
        "PlacementGroupInfo": {"SupportedStrategies": ["partition", "spread"]},
        "HibernationSupported": True,
        "BurstablePerformanceSupported": True,
        "DedicatedHostsSupported": False,
        "AutoRecoverySupported": True,
        "SupportedBootModes": ["uefi"],
        "NitroEnclavesSupport": "unsupported",
        "NitroTpmSupport": "supported",
        "NitroTpmInfo": {"SupportedVersions": ["2.0"]},
    },
]

PRICING_DATA = [
    {
        "AvailabilityZone": "eu-north-1b",
        "InstanceType": "m6idn.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.038000",
        "Timestamp": datetime.datetime(2024, 5, 8, 9, 31, 30, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1a",
        "InstanceType": "m6idn.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.053100",
        "Timestamp": datetime.datetime(2024, 5, 8, 8, 31, 27, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1a",
        "InstanceType": "r6gd.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.023700",
        "Timestamp": datetime.datetime(2024, 5, 8, 7, 16, 44, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1b",
        "InstanceType": "r6gd.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.024700",
        "Timestamp": datetime.datetime(2024, 5, 8, 4, 1, 19, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1b",
        "InstanceType": "m6idn.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.038100",
        "Timestamp": datetime.datetime(2024, 5, 8, 3, 46, 31, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1b",
        "InstanceType": "m6idn.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.037900",
        "Timestamp": datetime.datetime(2024, 5, 8, 0, 16, 24, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1b",
        "InstanceType": "r6gd.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.024800",
        "Timestamp": datetime.datetime(2024, 5, 8, 0, 2, 20, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1a",
        "InstanceType": "r6gd.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.023600",
        "Timestamp": datetime.datetime(2024, 5, 7, 22, 1, 26, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1c",
        "InstanceType": "m6idn.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.038000",
        "Timestamp": datetime.datetime(2024, 5, 7, 19, 46, 37, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1a",
        "InstanceType": "m6idn.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.053000",
        "Timestamp": datetime.datetime(2024, 5, 7, 16, 31, 44, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1b",
        "InstanceType": "m6idn.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.037800",
        "Timestamp": datetime.datetime(2024, 5, 7, 14, 31, 15, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1a",
        "InstanceType": "m6idn.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.053100",
        "Timestamp": datetime.datetime(2024, 5, 7, 7, 46, 24, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1c",
        "InstanceType": "m6idn.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.037900",
        "Timestamp": datetime.datetime(2024, 5, 7, 5, 1, 30, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1b",
        "InstanceType": "r6gd.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.024800",
        "Timestamp": datetime.datetime(2024, 5, 7, 0, 1, 28, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1a",
        "InstanceType": "r6gd.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.023500",
        "Timestamp": datetime.datetime(2024, 5, 6, 23, 16, 56, tzinfo=tzutc()),
    },
    {
        "AvailabilityZone": "eu-north-1b",
        "InstanceType": "m6idn.large",
        "ProductDescription": "Linux/UNIX",
        "SpotPrice": "0.037600",
        "Timestamp": datetime.datetime(2024, 5, 6, 21, 31, 28, tzinfo=tzutc()),
    },
]

REGIONAL_PRICING_INFO = {
    "manifest": {
        "serviceId": "ec2",
        "accessType": "publish",
        "hawkFilePublicationDate": "2024-11-14T21:50:09Z",
        "ETLIngestionTriggerDate": "2024-11-14T21:50:09Z",
        "currencyCode": "USD",
        "source": "ec2-ondemand-without-sec-sel",
    },
    "regions": {
        "EU (Stockholm)": {
            "m6in large EU Stockholm Linux": {
                "rateCode": "PEEZJDSDVW22Q4FW.JRTCKXETXF.6YS6EN2CT7",
                "price": "0.1480000000",
                "Location": "EU (Stockholm)",
                "Instance Family": "General purpose",
                "vCPU": "2",
                "Instance Type": "m6in.large",
                "Memory": "8 GiB",
                "Storage": "EBS only",
                "Network Performance": "Up to 25000 Megabit",
                "plc:OperatingSystem": "Linux",
                "plc:InstanceFamily": "General Purpose",
                "Operating System": "Linux",
                "Pre Installed S/W": "NA",
                "License Model": "No License required",
            },
            "r7a 2xlarge EU Stockholm Linux": {
                "rateCode": "PASVXMSYCTZND8W3.JRTCKXETXF.6YS6EN2CT7",
                "price": "0.6472000000",
                "Location": "EU (Stockholm)",
                "Instance Family": "Memory optimized",
                "vCPU": "8",
                "Instance Type": "r7a.2xlarge",
                "Memory": "64 GiB",
                "Storage": "EBS only",
                "Network Performance": "Up to 12500 Megabit",
                "plc:OperatingSystem": "Linux",
                "plc:InstanceFamily": "Memory Optimized",
                "Operating System": "Linux",
                "Pre Installed S/W": "NA",
                "License Model": "No License required",
            },
            "i3 2xlarge EU Stockholm Linux": {
                "rateCode": "FUB7Q54ZGEMZPF29.JRTCKXETXF.6YS6EN2CT7",
                "price": "0.6520000000",
                "Location": "EU (Stockholm)",
                "Instance Family": "Storage optimized",
                "vCPU": "8",
                "Instance Type": "i3.2xlarge",
                "Memory": "61 GiB",
                "Storage": "1 x 1900 NVMe SSD",
                "Network Performance": "Up to 10 Gigabit",
                "plc:OperatingSystem": "Linux",
                "plc:InstanceFamily": "Storage Optimized",
                "Operating System": "Linux",
                "Pre Installed S/W": "NA",
                "License Model": "No License required",
            },
        }
    },
}


# https://website.spot.ec2.aws.a2z.com/spot.json
SPOT_PRICING_INFO_S3_JSON_SAMPLE = {
    "vers": 0.01,
    "config": {
        "rate": "perhr",
        "valueColumns": ["linux", "mswin"],
        "currencies": ["USD"],
        "regions": [
            {
                "region": "us-east-1",
                "footnotes": {"*": "notAvailableForCCorCGPU"},
                "instanceTypes": [
                    {
                        "type": "generalCurrentGen",
                        "sizes": [
                            {
                                "size": "m6i.xlarge",
                                "valueColumns": [
                                    {
                                        "name": "linux",
                                        "prices": {"USD": "0.0615"},
                                    },
                                    {
                                        "name": "mswin",
                                        "prices": {"USD": "0.2032"},
                                    },
                                ],
                            },
                            {
                                "size": "m6g.xlarge",
                                "valueColumns": [
                                    {
                                        "name": "linux",
                                        "prices": {"USD": "0.0378"},
                                    },
                                    {
                                        "name": "mswin",
                                        "prices": {"USD": "N/A*"},
                                    },
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    },
}

# From https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json
PUBLIC_EVICTION_RATE_INFO = {
    "global_rate": "<10%",
    "instance_types": {
        "r7g.xlarge": {"emr": True, "cores": 4, "ram_gb": 32.0},
        "c8g.16xlarge": {"emr": True, "cores": 64, "ram_gb": 128.0},
        "c8g.48xlarge": {"emr": True, "cores": 192, "ram_gb": 384.0},
        "g4ad.8xlarge": {"emr": False, "cores": 32, "ram_gb": 128.0},
        "g4ad.16xlarge": {"emr": False, "cores": 64, "ram_gb": 256.0},
    },
    "ranges": [
        {"index": 0, "label": "<5%", "dots": 0, "max": 5},
        {"index": 1, "label": "5-10%", "dots": 1, "max": 11},
        {"index": 2, "label": "10-15%", "dots": 2, "max": 16},
        {"index": 3, "label": "15-20%", "dots": 3, "max": 22},
        {"index": 4, "label": ">20%", "dots": 4, "max": 100},
    ],
    "spot_advisor": {
        "eu-north-1": {
            "Linux": {
                "r5dn.24xlarge": {"s": 73, "r": 2},
                "m7gd.8xlarge": {"s": 74, "r": 1},
                "m7a.16xlarge": {"s": 71, "r": 3},
                "c6gd.medium": {"s": 73, "r": 1},
                "r7g.large": {"s": 70, "r": 0},
                "c6gd.8xlarge": {"s": 73, "r": 0},
                "r7a.2xlarge": {"s": 70, "r": 0},
                "t3.large": {"s": 69, "r": 0},
                "m6g.12xlarge": {"s": 74, "r": 0},
            }
        }
    },
}


def test_filter_instances():
    iti = boto3_api_instance_list_to_instance_type_info(
        "dummy-reg", INSTANCE_LISTING
    )
    assert len(iti) == 4
    filtered = filter_instance_types_by_hw_req(
        iti,
        storage_min=10,
        storage_type=MF_SEC_VM_STORAGE_TYPE_LOCAL,
    )
    assert len(filtered) == 2

    filtered_no_filters = filter_instance_types_by_hw_req(
        iti,
    )
    assert len(filtered_no_filters) == 4

    filtered_instance_family = filter_instance_types_by_hw_req(
        iti, instance_family="t4"
    )
    assert len(filtered_instance_family) == 1

    filtered_instance_family = filter_instance_types_by_hw_req(
        iti, instance_family="gd"
    )
    assert len(filtered_instance_family) == 2


def test_get_avg_spot_price_from_pricing_history_data_by_sku_and_az():
    sku_az_price_data = (
        aws_spot.get_avg_spot_price_from_pricing_history_data_by_sku_and_az(
            PRICING_DATA
        )
    )
    assert len(sku_az_price_data) == 5
    assert sku_az_price_data[0][0] == "r6gd.large"


def test_get_current_spot_price():
    sp = get_current_hourly_spot_price_boto3(
        "eu-north-1", "m6idn.large", "eu-north-1a", PRICING_DATA
    )
    assert 0.01 < sp < 1


@unittest.SkipTest
def test_get_current_hourly_ondemand_price():
    sp = get_current_hourly_ondemand_price("eu-north-1", "i3.xlarge")
    assert 0.1 < sp < 10


def test_resolve_instance_type_info():
    i_info = resolve_instance_type_info(
        "i3.xlarge", "eu-north-1", "eu-north-1c", i_desc=INSTANCE_LISTING[0]
    )
    assert i_info.cpu == 1
    assert i_info.ram_mb == 8192
    assert i_info.instance_storage == 59
    assert i_info.storage_speed_class == "ssd"
    assert i_info.availability_zone == "eu-north-1c"


def test_get_ondemand_price_for_instance_type_from_aws_regional_pricing_info():
    assert (
        get_ondemand_price_for_instance_type_from_aws_regional_pricing_info(
            "eu-north-1", "r7a.2xlarge", REGIONAL_PRICING_INFO
        )
        > 0
    )


def test_instance_info_parsing():
    all_instances = get_all_instance_types_from_aws_regional_pricing_info(
        "eu-north-1", REGIONAL_PRICING_INFO
    )
    by_instance_type = {x.instance_type: x for x in all_instances}
    assert by_instance_type["i3.2xlarge"].arch == CPU_ARCH_X86


def test_get_spot_instance_types_with_price_from_s3_pricing_json():
    x = get_spot_instance_types_with_price_from_s3_pricing_json(
        "us-east-1", SPOT_PRICING_INFO_S3_JSON_SAMPLE
    )
    assert len(x) == 2
    assert x["m6g.xlarge"] > 0.01


def test_extract_memory_mb_from_aws_pricing_memory_string():
    assert extract_memory_mb_from_aws_pricing_memory_string("64 GiB") == int(
        64 * 1024
    )
    assert extract_memory_mb_from_aws_pricing_memory_string("512 MiB") == 512
    assert extract_memory_mb_from_aws_pricing_memory_string("1 TiB") == int(
        1 * 1024 * 1024
    )


def test_eviction_rate_group_to_label():
    ev_grp_map = get_eviction_rate_brackets_from_public_eviction_info(
        public_eviction_rate_info=PUBLIC_EVICTION_RATE_INFO
    )
    assert ev_grp_map[0]["label"] == "<5%"
    assert ev_grp_map[4]["label"] == ">20%"
    assert (
        get_eviction_rate_brackets_from_public_eviction_info(
            public_eviction_rate_info={"x": 1}
        )
        == {}
    )


def test_extract_instance_type_eviction_rates_from_public_eviction_info():
    evi = extract_instance_type_eviction_rates_from_public_eviction_info(
        list(PUBLIC_EVICTION_RATE_INFO["spot_advisor"].keys())[0],
        PUBLIC_EVICTION_RATE_INFO,
    )
    assert evi
    assert len(evi) == 9
    assert evi["r7g.large"].eviction_rate_group == 0
