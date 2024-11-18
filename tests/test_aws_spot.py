import datetime
import unittest

from dateutil.tz import tzutc

from pg_spot_operator.cloud_impl import aws_spot
from pg_spot_operator.cloud_impl.aws_spot import (
    get_current_hourly_spot_price,
    get_current_hourly_ondemand_price,
    filter_instance_types_by_hw_req,
    resolve_instance_type_info,
    get_ondemand_price_for_instance_type_from_aws_regional_pricing_info,
    get_spot_instance_types_with_price_from_s3_pricing_json,
)
from pg_spot_operator.constants import MF_SEC_VM_STORAGE_TYPE_LOCAL

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


def test_filter_instances():
    assert len(INSTANCE_LISTING) == 4
    filtered = filter_instance_types_by_hw_req(
        INSTANCE_LISTING,
        storage_min=10,
        storage_type=MF_SEC_VM_STORAGE_TYPE_LOCAL,
    )
    assert len(filtered) == 2

    filtered = filter_instance_types_by_hw_req(
        INSTANCE_LISTING,
    )
    assert len(filtered) == 4


def test_get_avg_spot_price_from_pricing_history_data_by_sku_and_az():
    sku_az_price_data = (
        aws_spot.get_avg_spot_price_from_pricing_history_data_by_sku_and_az(
            PRICING_DATA
        )
    )
    assert len(sku_az_price_data) == 5
    assert sku_az_price_data[0][0] == "r6gd.large"


def test_get_current_spot_price():
    sp = get_current_hourly_spot_price(
        "eu-north-1", "m6idn.large", "eu-north-1a", PRICING_DATA
    )
    assert 0.01 < sp < 1


@unittest.SkipTest
def test_get_current_hourly_ondemand_price():
    sp = get_current_hourly_ondemand_price("eu-north-1", "i3.xlarge")
    assert 0.1 < sp < 10


def test_resolve_instance_type_info():
    i_info = resolve_instance_type_info(
        "i3.xlarge", "eu-north-1", i_desc=INSTANCE_LISTING[0]
    )
    assert i_info.cpu == 1
    assert i_info.ram_mb == 8192
    assert i_info.instance_storage == 59
    assert i_info.storage_speed_class == "ssd"


def test_get_ondemand_price_for_instance_type_from_aws_regional_pricing_info():
    assert (
        get_ondemand_price_for_instance_type_from_aws_regional_pricing_info(
            "eu-north-1", "r7a.2xlarge", REGIONAL_PRICING_INFO
        )
        > 0
    )


def test_get_spot_instance_types_with_price_from_s3_pricing_json():
    x = get_spot_instance_types_with_price_from_s3_pricing_json(
        "us-east-1", SPOT_PRICING_INFO_S3_JSON_SAMPLE
    )
    assert len(x) == 2
    assert x["m6g.xlarge"] > 0.01
