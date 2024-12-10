import logging
import os
import time
from datetime import datetime
from typing import Any

import botocore

from pg_spot_operator.cloud_impl.aws_client import get_client
from pg_spot_operator.cloud_impl.cloud_structs import CloudVM, InstanceTypeInfo
from pg_spot_operator.constants import CLOUD_AWS
from pg_spot_operator.manifests import InstanceManifest

# Attached to all created cloud resources
SPOT_OPERATOR_ID_TAG = "pg-spot-operator-instance"
STORAGE_TYPE_NETWORK = "network"
MAX_WAIT_SECONDS: int = 300
LOGIN_USER = "pgspotops"
OS_IMAGE_FAMILY = "debian-12"


logger = logging.getLogger(__name__)


def str_to_bool(in_str: str) -> bool:
    if not in_str:
        return False
    if in_str.lower() in ["t", "true", "on", "1"]:
        return True
    return False


def get_latest_ami_for_region_arch(
    region: str, architecture: str
) -> tuple[str, dict]:
    """AMI names look like below and search API accepts a wildcard in the end
    debian-12-amd64-20230711-1438
    ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-20240411
    ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-20240423
    Returns (image ID, AMI details dict)
    """
    logger.debug(
        f"Getting AMI for region {region} architecture {architecture} os_family {OS_IMAGE_FAMILY} ..."
    )

    client = get_client("ec2", region)

    if "arm" in architecture.lower():
        architecture = "arm64"
    else:
        architecture = "amd64"

    ami_name_search_str = f"{OS_IMAGE_FAMILY}-{architecture}-*"

    cur_year = datetime.now().year
    years = [cur_year, cur_year - 1]  # To cover beginning of year

    for year in years:
        response = client.describe_images(
            Filters=[
                {
                    "Name": "name",
                    "Values": [
                        ami_name_search_str,
                    ],
                },
                {
                    "Name": "creation-date",
                    "Values": [
                        f"{year}*",
                    ],
                },
            ],
            Owners=[
                "amazon",
            ],
            IncludeDeprecated=False,
            IncludeDisabled=False,
        )

        if response["Images"]:
            amis = response["Images"]
            amis.sort(key=lambda x: x["CreationDate"], reverse=True)
            logger.debug("Latest %s AMI found: %s", OS_IMAGE_FAMILY, amis[0])
            return amis[0]["ImageId"], amis[0]
    raise Exception(
        f"No default AMI found for region {region}, architecture {architecture}, os_family {OS_IMAGE_FAMILY}"
    )


def create_new_volume_for_instance(
    region: str,
    availability_zone: str,
    instance_id: str,
    volume_size_min: int,
    volume_type: str = "gp3",
    volume_iops: int = 0,
    volume_throughput: int = 0,
) -> dict:
    """https://docs.aws.amazon.com/cli/latest/reference/ec2/create-volume.html"""
    client = get_client("ec2", region)

    logger.debug(
        f"Creating a new {volume_size_min} GB EBS volume for instance {instance_id} in AZ {availability_zone} ... "
    )

    tags = [{"Key": SPOT_OPERATOR_ID_TAG, "Value": instance_id}]

    kwargs = {}
    if volume_iops:
        kwargs["Iops"] = int(volume_iops)
    if volume_throughput:
        kwargs["Throughput"] = int(volume_throughput)

    resp = client.create_volume(
        AvailabilityZone=availability_zone,
        Encrypted=True,
        Size=int(volume_size_min),
        VolumeType=volume_type,
        TagSpecifications=[
            {"ResourceType": "volume", "Tags": tags},
        ],
        **kwargs,
    )

    logger.debug("OK. New volume ID: %s", resp["VolumeId"])
    return resp


def attach_volume_to_instance(
    region: str,
    vol_id: str,
    instance_id: str,
    wait_till_attached_max_seconds: int = 30,
) -> None:
    client = get_client("ec2", region)

    tries = 2
    while tries:
        try:
            logger.debug(f"Checking vol {vol_id} attachment status ...")
            resp_desc = client.describe_volumes(VolumeIds=[vol_id])
            if (
                resp_desc
                and resp_desc.get("Volumes")
                and resp_desc["Volumes"][0]["Attachments"]
            ):
                if (
                    resp_desc["Volumes"][0]["Attachments"][0]["State"]
                    == "attached"
                ):
                    logger.debug("OK - already attached")
                    return

            if not resp_desc["Volumes"][0]["Attachments"]:
                logger.debug(
                    f"Attaching vol {vol_id} to instance {instance_id} ..."
                )
                client.attach_volume(
                    Device="/dev/xvdb",
                    InstanceId=instance_id,
                    VolumeId=vol_id,
                )
                break

        except Exception as e:
            logger.debug(e)
        finally:
            tries -= 1

        time.sleep(1)

    if wait_till_attached_max_seconds:
        logger.debug(
            f"Waiting up to {wait_till_attached_max_seconds}s till vol {vol_id} attached ..."
        )
        start_time = time.time()
        while time.time() < start_time + wait_till_attached_max_seconds:
            resp_desc = client.describe_volumes(VolumeIds=[vol_id])
            if (
                resp_desc
                and resp_desc.get("Volumes")
                and resp_desc["Volumes"][0]["Attachments"]
            ):
                if (
                    resp_desc["Volumes"][0]["Attachments"][0]["State"]
                    == "attached"
                ):
                    logger.debug("OK - attached")
                    return
            time.sleep(5)

    raise Exception(f"Could not attach vol {vol_id} to instance {instance_id}")


def ensure_public_elastic_ip_attached(
    region: str, instance_name: str, instance_id: str
) -> str:
    """Allocates a public elastic IP if not yet and assigns to the input instance_id.
    Returns the public IP on success.
    https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html#eip-basics
    https://docs.aws.amazon.com/cli/latest/reference/ec2/allocate-address.html
    """
    client = get_client("ec2", region)

    tag_filter = {
        "Name": "tag:" + SPOT_OPERATOR_ID_TAG,
        "Values": [
            instance_name,
        ],
    }
    desc_response = client.describe_addresses(Filters=[tag_filter])

    pip: str = ""
    allocation_id: str = ""
    if desc_response and desc_response.get("Addresses"):
        pip = desc_response.get("Addresses")[0]["PublicIp"]
        allocation_id = desc_response.get("Addresses")[0]["AllocationId"]
        logger.debug("An existing elastic IP found: %s", pip)

    if not pip:
        logger.debug("Assign a new elastic IP in region %s", region)
        response = client.allocate_address(
            TagSpecifications=[
                {
                    "ResourceType": "elastic-ip",
                    "Tags": [
                        {"Key": SPOT_OPERATOR_ID_TAG, "Value": instance_name},
                    ],
                },
            ]
        )
        if not response or not response.get("PublicIp"):
            raise Exception(
                f"Could not allocate a new public IP for instance {instance_id} in region {region}"
            )
        pip = response["PublicIp"]
        allocation_id = response["AllocationId"]

    logger.debug(f"Assigning IP {pip} to instance {instance_id} ...")
    client.associate_address(
        AllocationId=allocation_id,
        InstanceId=instance_id,
    )

    return pip


def get_key_pair_pubkey_if_any(region: str, ssh_key_pair_name: str) -> str:
    """Swallows the exception if can't read out the actual pubkey as there are ways to specify keys"""
    if not ssh_key_pair_name:
        return ""
    client = get_client("ec2", region)
    try:
        response = client.describe_key_pairs(
            KeyNames=[
                ssh_key_pair_name,
            ],
            IncludePublicKey=True,
        )
        if response and "KeyPairs" in response:
            return response["KeyPairs"][0]["PublicKey"].rstrip()
    except Exception:
        logger.exception(f"Failed to describe key pair {ssh_key_pair_name}")
    return ""


def compile_cloud_init_user_data_config(
    region: str,
    login_user: str,
    default_ssh_key_path: str,
    ssh_keys: list[str],
    ssh_key_pair_name: str = "",
) -> str:
    default_ssh_key = read_ssh_key_from_path(default_ssh_key_path)
    aws_key_pair_key = get_key_pair_pubkey_if_any(region, ssh_key_pair_name)

    cloud_init = f"""
#cloud-config
cloud_final_modules:
- [users-groups,always]
users:
  - name: {login_user}
    sudo:
      - "ALL=(ALL) NOPASSWD:ALL"
    shell: /bin/bash
    ssh-authorized-keys:
"""
    if default_ssh_key:
        cloud_init += f"    - {default_ssh_key}\n"
    if aws_key_pair_key:
        cloud_init += f"    - {aws_key_pair_key}\n"
    for key in ssh_keys:
        cloud_init += f"    - {key}\n"
    return cloud_init


def get_nic_id_if_any_by_id_tag(instance_name: str, region: str) -> str:
    client = get_client("ec2", region)

    filters = [
        {
            "Name": "tag:" + SPOT_OPERATOR_ID_TAG,
            "Values": [
                instance_name,
            ],
        },
    ]

    response = client.describe_network_interfaces(Filters=filters)
    if response and response.get("NetworkInterfaces"):
        return response["NetworkInterfaces"][0]["NetworkInterfaceId"]
    return ""


def wait_until_nic_available(
    nic_id: str, region: str, max_wait_seconds: int = 300
) -> None:
    """Throws an exception when volume not "available" in max_wait_seconds
    https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-volumes.html
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_volumes.html#describe-volumes
    """
    start_time = time.time()
    while time.time() < (start_time + max_wait_seconds):
        try:
            client = get_client("ec2", region)

            logger.debug(f"Checking NetworkInterface {nic_id} state ...")
            resp = client.describe_network_interfaces(
                NetworkInterfaceIds=[nic_id]
            )
            if resp and resp.get("NetworkInterfaces"):
                if resp["NetworkInterfaces"][0]["Status"] == "available":
                    logger.debug(
                        "OK %s %s",
                        resp["NetworkInterfaces"][0]["Status"],
                        datetime.now(),
                    )
                    time.sleep(1)
                    return
                logger.debug(
                    "Not OK %s %s",
                    resp["NetworkInterfaces"][0]["Status"],
                    datetime.now(),
                )
                time.sleep(10)
        except Exception as e:
            logger.debug(e)
            time.sleep(10)
    raise Exception(
        f"NetworkInterface {nic_id} not in 'available' state within {max_wait_seconds}"
    )


def ec2_launch_instance(
    m: InstanceManifest,
    rit: InstanceTypeInfo,
    user_data: str = "",
    dry_run: bool = False,
) -> dict:
    """https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/run_instances.html
    Returns full instance description dict from the API
    """
    instance_name: str = m.instance_name
    region: str = m.region
    availability_zone: str = rit.availability_zone
    user_tags: dict = m.user_tags
    architecture: str = rit.arch
    instance_type: str = rit.instance_type
    key_pair_name: str = m.aws.key_pair_name
    security_group_ids: list[str] = m.aws.security_group_ids
    subnet_id: str = m.aws.subnet_id
    market_type = "spot"

    if not region:
        raise Exception("Instance manifest 'region' input required!")

    if SPOT_OPERATOR_ID_TAG not in user_tags:
        user_tags[SPOT_OPERATOR_ID_TAG] = instance_name
    if "Name" not in user_tags:  # For better clarity in the Web console
        user_tags["Name"] = f"{instance_name} [pg-spot-operator]"
    os_image_id, _ = get_latest_ami_for_region_arch(region, architecture)

    placement = {}
    if availability_zone:
        placement["AvailabilityZone"] = availability_zone
    if m.vm.storage_type == STORAGE_TYPE_NETWORK:
        # Need to create replacement VMs in the same AZ as the volume
        vol_desc = get_existing_data_volume_for_instance_if_any(
            region, instance_name
        )
        if vol_desc:
            placement["AvailabilityZone"] = vol_desc["AvailabilityZone"]
    logger.debug("placement %s", placement)

    network_interface: dict[str, Any] = {
        "AssociatePublicIpAddress": False,
        "DeviceIndex": 0,
        "DeleteOnTermination": m.ip_floating,
    }
    if m.ip_floating and m.assign_public_ip:
        network_interface["AssociatePublicIpAddress"] = True
    if subnet_id:
        network_interface["SubnetId"] = subnet_id
    if security_group_ids:
        network_interface["Groups"] = security_group_ids
    logger.debug("network_interface %s", network_interface)

    existing_nic_found = False
    if not m.ip_floating:
        nic_id = get_nic_id_if_any_by_id_tag(instance_name, region)
        if nic_id:
            existing_nic_found = True
            wait_until_nic_available(nic_id, region)
            network_interface = {
                "DeviceIndex": 0,
                "DeleteOnTermination": False,
                "NetworkInterfaceId": nic_id,
            }

    kwargs_run: dict[str, Any] = {}
    if instance_type.startswith("t"):
        # Avoid instant priced "turbo boost" for burstable instances that haven't accrued CPU credits yet
        # CreditSpecification param not allowed for non-burstable instances
        kwargs_run["CreditSpecification"] = {"CpuCredits": "standard"}
    if user_data:
        kwargs_run["UserData"] = user_data
    if key_pair_name:
        kwargs_run["KeyName"] = key_pair_name

    tags_kv_list = []
    for k, v in user_tags.items():
        tags_kv_list.append({"Key": k, "Value": v})
    tag_spec = [
        {"ResourceType": "instance", "Tags": tags_kv_list},
    ]
    if not existing_nic_found:
        tag_spec.append(
            {
                "ResourceType": "network-interface",
                "Tags": [
                    {
                        "Key": SPOT_OPERATOR_ID_TAG,
                        "Value": instance_name,
                    }
                ],
            }
        )

    logger.info(
        f"Launching a new {market_type} instance of type {instance_type} in region {region} ..."
    )

    client = get_client("ec2", region)
    logger.debug("kwargs_run: %s", kwargs_run)
    logger.debug("tag_spec: %s", tag_spec)

    try:
        i = client.run_instances(
            BlockDeviceMappings=[
                {
                    "DeviceName": "/dev/xvda",
                    "Ebs": {
                        "DeleteOnTermination": True,
                        "VolumeSize": 20,
                        "VolumeType": "gp3",
                        "Encrypted": True,
                    },
                },
            ],
            InstanceType=instance_type,
            MinCount=1,
            MaxCount=1,
            ImageId=os_image_id,
            InstanceMarketOptions={"MarketType": market_type},
            Placement=placement,
            NetworkInterfaces=[network_interface],
            TagSpecifications=tag_spec,
            Monitoring={"Enabled": m.vm.detailed_monitoring},
            DryRun=dry_run,
            **kwargs_run,
        )  # type: dict
    except botocore.exceptions.ClientError as e:
        if dry_run and "but DryRun flag is set" in str(e):
            return {}
        else:
            raise

    if dry_run:
        return {}

    i_id = i["Instances"][0]["InstanceId"]
    i_az = i["Instances"][0]["Placement"]["AvailabilityZone"]
    logger.debug(
        f"New {market_type} {instance_type} instance {i_id} launched in AZ {i_az}"
    )
    logger.debug("Waiting for instance 'running' state (timeout 300s) ...")

    resp: dict = {}
    i_desc: dict = {}
    t1 = time.time()
    while time.time() < t1 + MAX_WAIT_SECONDS:
        try:
            resp = client.describe_instances(InstanceIds=[i_id])
            if resp:
                i_desc = resp["Reservations"][0]["Instances"][0]
                if i_desc["State"]["Name"] == "running":
                    time.sleep(1)
                    break
        except Exception as e:
            logger.debug(e)
        time.sleep(5)
    if time.time() > t1 + MAX_WAIT_SECONDS:
        logger.debug(
            f"Timed out waiting for instance {i_id} to become runnable"
        )
        logger.debug("Last API response: %s", resp)
        return {}
    logger.debug("OK - instance running. Desc: %s", i_desc)

    return i_desc


def read_ssh_key_from_path(key_path: str) -> str:
    key_path = os.path.expanduser(key_path)
    if not os.path.exists(key_path):
        logger.warning(
            f"SSH pubkey at {key_path} not found, might not be able to access the VM later"
        )
        return ""
    if not os.path.isfile(key_path):
        logger.warning(
            f"SSH pubkey at {key_path} not a file, might not be able to access the VM later"
        )
        return ""
    logger.debug("Reading SSH key from path: %s", key_path)

    with open(key_path) as f:
        return f.read().rstrip()


def get_running_instance_by_tags(region: str, tags: dict) -> dict:
    """https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_instances.html#describe-instances
    Returns a dict looking like that: aws ec2 describe-instances | jq '.Reservations[0].Instances[0]'
    Tags can be filtered with keys like: tag:<key>
    """
    try:
        client = get_client("ec2", region)

        filters = [
            {"Name": "instance-state-name", "Values": ["pending", "running"]}
        ]
        for k, v in tags.items():
            filters.append(
                {
                    "Name": f"tag:{k}",
                    "Values": [
                        v,
                    ],
                }
            )
        resp = client.describe_instances(Filters=filters)
        if resp and resp.get("Reservations"):
            return resp["Reservations"][0]["Instances"][0]
    except Exception as e:
        logger.debug(e)
    return {}


def get_all_active_operator_instances_in_region(region: str) -> list[str]:
    """Return all non-terminated instances. Instance state descriptions:
    https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html
    """
    client = get_client("ec2", region)

    filters = [
        {
            "Name": "instance-state-name",
            "Values": [
                "pending",
                "running",
                "shutting-down",
                "stopping",
                "stopped",
            ],
        },
        {"Name": "tag-key", "Values": [SPOT_OPERATOR_ID_TAG]},
    ]

    paginator = client.get_paginator("describe_instances")

    page_iterator = paginator.paginate(Filters=filters)

    instance_ids = []
    for page in page_iterator:
        for r in page.get("Reservations", []):
            for i in r.get("Instances", []):
                instance_ids.append(i["InstanceId"])
    return instance_ids


def get_operator_volumes_in_region(
    region: str, instance_name: str = ""
) -> list[tuple[str, int]]:
    """Returns [(volId, size),...]"""
    client = get_client("ec2", region)

    if instance_name:
        filters = [
            {"Name": f"tag:{SPOT_OPERATOR_ID_TAG}", "Values": [instance_name]},
        ]
    else:
        filters = [
            {"Name": "tag-key", "Values": [SPOT_OPERATOR_ID_TAG]},
        ]
    resp = client.describe_volumes(Filters=filters)
    if resp and resp.get("Volumes"):
        return [(x["VolumeId"], x["Size"]) for x in resp["Volumes"]]
    return []


def get_addresses(region: str, instance_name: str = "") -> list[str]:
    """Returns a list of AllocationId-s"""
    client = get_client("ec2", region)

    if instance_name:
        filters = [
            {"Name": f"tag:{SPOT_OPERATOR_ID_TAG}", "Values": [instance_name]},
        ]
    else:
        filters = [
            {"Name": "tag-key", "Values": [SPOT_OPERATOR_ID_TAG]},
        ]
    resp = client.describe_addresses(Filters=filters)
    if resp and resp.get("Addresses"):
        return [x["AllocationId"] for x in resp["Addresses"]]
    return []


def get_non_self_terminating_network_interfaces(
    region: str, instance_name: str = ""
) -> list[str]:
    client = get_client("ec2", region)

    if instance_name:
        filters = [
            {"Name": f"tag:{SPOT_OPERATOR_ID_TAG}", "Values": [instance_name]},
        ]
    else:
        filters = [
            {"Name": "tag-key", "Values": [SPOT_OPERATOR_ID_TAG]},
        ]
    resp = client.describe_network_interfaces(Filters=filters)
    if resp and resp.get("NetworkInterfaces"):
        return [
            x["NetworkInterfaceId"]
            for x in resp["NetworkInterfaces"]
            if not x.get("Attachment", {}).get("DeleteOnTermination")
        ]
    return []


def terminate_instances_in_region(
    region: str, instance_ids: list[str]
) -> None:
    client = get_client("ec2", region)
    client.terminate_instances(InstanceIds=instance_ids)


def delete_volume_in_region(region: str, vol_id: str) -> None:
    client = get_client("ec2", region)
    client.delete_volume(VolumeId=vol_id)


def release_address_by_allocation_id_in_region(
    region: str, alloc_id: str
) -> None:
    client = get_client("ec2", region)
    client.release_address(AllocationId=alloc_id)


def delete_network_interface(region: str, nic_id: str) -> None:
    client = get_client("ec2", region)
    client.delete_network_interface(NetworkInterfaceId=nic_id)


def get_existing_data_volume_for_instance_if_any(
    region: str, instance_name: str
) -> dict:
    """https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_volumes.html#describe-volumes
    {
        "Attachments": [
            {
                "AttachTime": "2024-06-04T08:41:21+00:00",
                "Device": "/dev/xvdb",
                "InstanceId": "i-0147a78c5bd4e0300",
                "State": "attached",
                "VolumeId": "vol-031735e54116b9f75",
                "DeleteOnTermination": false
            }
        ],
        "AvailabilityZone": "eu-north-1c",
        "CreateTime": "2024-06-04T08:30:39.757000+00:00",
        "Encrypted": true,
        "KmsKeyId": "arn:aws:kms:eu-north-1:416747137388:key/c29ccbe2-cd13-4ae6-8902-7a977066a1fe",
        "Size": 25,
        "SnapshotId": "",
        "State": "in-use",
        "VolumeId": "vol-031735e54116b9f75",
        "Iops": 3000,
        "Tags": [
            {
                "Key": "pg-spot-operator-instance",
                "Value": "spot1"
            }
        ],
        "VolumeType": "gp3",
        "MultiAttachEnabled": false,
        "Throughput": 125
    }
    """
    try:
        client = get_client("ec2", region)

        filters = [
            {
                "Name": "tag:" + SPOT_OPERATOR_ID_TAG,
                "Values": [
                    instance_name,
                ],
            },
        ]
        resp = client.describe_volumes(Filters=filters)
        if resp and resp.get("Volumes"):
            if len(resp.get("Volumes")) > 1:
                raise Exception(
                    "Expecting a single volume only currently per instance"
                )
            return resp["Volumes"][0]
    except Exception as e:
        logger.debug(e)
    return {}


def wait_until_volume_available(
    region: str, volume_id: str, max_wait_seconds: int
) -> None:
    """Throws an exception when volume not in attachable state in max_wait_seconds
    https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-volumes.html
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_volumes.html#describe-volumes
    """
    start_time = time.time()
    while time.time() < (start_time + max_wait_seconds):
        try:
            client = get_client("ec2", region)

            logger.debug(f"Checking volume {volume_id} state ...")
            resp = client.describe_volumes(VolumeIds=[volume_id])
            if resp and resp.get("Volumes"):
                if resp["Volumes"][0]["State"] == "available":
                    logger.debug("OK - %s", resp["Volumes"][0]["State"])
                    return None
                logger.debug("Not OK - %s", resp["Volumes"][0]["State"])
                time.sleep(10)
        except Exception as e:
            logger.debug(e)
            time.sleep(10)
    raise Exception(
        f"Volume {volume_id} not in 'available' state within {max_wait_seconds}"
    )


def ensure_volume_attached(m: InstanceManifest, instance_desc: dict) -> dict:
    """Returns an EC2 describe_volumes dict"""
    instance_id: str = instance_desc["InstanceId"]
    instance_name: str = m.instance_name
    az = instance_desc["Placement"]["AvailabilityZone"]
    region: str = m.region
    storage_min: int = m.vm.storage_min
    volume_type: str = m.vm.volume_type
    volume_iops: int = m.vm.volume_iops
    volume_throughput: int = m.vm.volume_throughput

    logger.debug(f"Ensuring instance {instance_name} has a data volume ...")
    vol_desc = get_existing_data_volume_for_instance_if_any(
        region, instance_name
    )

    if vol_desc:

        if (
            vol_desc.get("Attachments")
            and vol_desc["Attachments"][0]["InstanceId"] == instance_id
        ):
            logger.debug(
                f"Volume {vol_desc['VolumeId']} already attached to instance {instance_id}"
            )
            return vol_desc

        if (
            vol_desc["State"] != "available"
        ):  # As it can take a bit of time for abrupt terminations
            wait_until_volume_available(region, vol_desc["VolumeId"], 120)

    else:
        vol_desc = create_new_volume_for_instance(
            region,
            az,
            instance_name,
            storage_min,
            volume_type,
            volume_iops,
            volume_throughput,
        )

        time.sleep(1)

    attach_volume_to_instance(region, vol_desc["VolumeId"], instance_id)

    return get_existing_data_volume_for_instance_if_any(region, instance_name)


def get_subnet_id_for_vpc_az(region: str, vpc_id: str, az: str) -> str:
    """Look for a default subnet, otherwise just take first in available state.
    Throw an error if none found
    """
    client = get_client("ec2", region)

    logger.debug(
        "Looking for a default subnet in VPC %s AZ %s ...", vpc_id, az
    )
    response = client.describe_subnets(
        Filters=[
            {
                "Name": "vpc-id",
                "Values": [
                    vpc_id,
                ],
            },
            {
                "Name": "availability-zone",
                "Values": [
                    az,
                ],
            },
        ],
    )
    for sn in response.get("Subnets", []):
        if sn.get("DefaultForAz"):
            logger.debug("OK - found default subnet: %s", sn["SubnetId"])
            return sn["SubnetId"]
    # If no default found (is possible even?)
    for sn in response.get("Subnets", []):
        if sn["State"] == "available":
            logger.debug("Chose non-default subnet: %s", sn["SubnetId"])
            return sn["SubnetId"]
    raise Exception(f"No subnets found for VPC {vpc_id} in Zone {az}")


def get_default_vpc(region: str) -> str:
    client = get_client("ec2", region)
    logger.debug("Fetching the default VPC for region %s ...", region)
    result = client.describe_vpcs(
        Filters=[{"Name": "is-default", "Values": ["true"]}]
    )
    if result.get("Vpcs"):
        # logger.debug("OK - default VPC: %s", result["Vpcs"][0]["VpcId"])
        return result["Vpcs"][0]["VpcId"]
    return ""


def ensure_spot_vm(
    m: InstanceManifest,
    resolved_instance_types: list[InstanceTypeInfo],
    dry_run: bool = False,
) -> tuple[CloudVM, bool]:
    """Returns [CloudVM, was_actually_created].
    Tries resolved instance types one-by-one if fails due to no capacity available
    """
    instance_name = m.instance_name
    region = m.region
    logger.debug("Ensuring a Spot VM for instance '%s' ...", instance_name)
    logger.debug(
        "Instance types to be tried: %s",
        [
            (x.instance_type, x.availability_zone)
            for x in resolved_instance_types
        ],
    )

    i_desc = get_running_instance_by_tags(
        m.region, {SPOT_OPERATOR_ID_TAG: instance_name}
    )
    vol_desc = {}
    new_vm_created = False

    if i_desc:
        logger.debug(
            f"Instance {i_desc['InstanceId']} already running for instance {instance_name}, skipping create"
        )
    else:
        for rit in resolved_instance_types:
            try:
                pub_key_file = "~/.ssh/id_rsa.pub"
                if m.ansible.private_key:
                    if m.ansible.private_key.endswith(".pub"):
                        pub_key_file = m.ansible.private_key
                    else:
                        pub_key_file = m.ansible.private_key + ".pub"
                user_data = compile_cloud_init_user_data_config(
                    region,
                    LOGIN_USER,
                    pub_key_file,
                    m.os.ssh_pub_keys,
                    m.aws.key_pair_name,
                )
                if m.aws.vpc_id and not m.aws.subnet_id:
                    if m.aws.vpc_id != get_default_vpc(region):
                        m.aws.subnet_id = get_subnet_id_for_vpc_az(
                            region, m.aws.vpc_id, m.availability_zone
                        )

                i_desc = ec2_launch_instance(
                    m, rit, dry_run=dry_run, user_data=user_data
                )
                if not dry_run:
                    new_vm_created = True
                    logger.debug("VM %s created", i_desc["InstanceId"])

                if dry_run:
                    logger.info("Dry-run launch OK")
                    return (
                        CloudVM(
                            provider_id="dummy",
                            cloud=CLOUD_AWS,
                            region=region,
                            instance_type=(
                                i_desc["InstanceType"]
                                if i_desc
                                else (
                                    m.vm.instance_types[0]
                                    if m.vm.instance_types
                                    else "N/A"
                                )
                            ),
                            login_user=LOGIN_USER,
                            ip_private="dummy",
                        ),
                        False,
                    )
                break
            except Exception as e:
                if "InsufficientInstanceCapacity" in str(e):
                    logger.error(
                        "Failed to launch - no Spot capacity available for %s in AZ %s",
                        rit.instance_type,
                        rit.availability_zone,
                    )
                else:
                    logger.exception("Failed to launch an instance")
                time.sleep(1)

    if not i_desc:
        raise Exception("No running instance found / failed to launch")

    if m.vm.storage_type == STORAGE_TYPE_NETWORK:
        vol_desc = ensure_volume_attached(m, i_desc)

    if m.assign_public_ip and not m.ip_floating:
        pip = ensure_public_elastic_ip_attached(
            region, instance_name, i_desc["InstanceId"]
        )
        logger.debug(
            f"Public IP {pip} assigned to instance {i_desc['InstanceId']}"
        )
        i_desc["PublicIpAddress"] = pip

    ret = CloudVM(
        provider_id=i_desc["InstanceId"],
        cloud=CLOUD_AWS,
        region=region,
        instance_type=i_desc["InstanceType"],
        login_user=LOGIN_USER,
        ip_private=i_desc["PrivateIpAddress"],
        ip_public=i_desc.get("PublicIpAddress", ""),
        availability_zone=i_desc["Placement"]["AvailabilityZone"],
        volume_id=vol_desc.get("VolumeId", ""),
        created_on=i_desc["LaunchTime"],
        provider_description=i_desc,
        volume_description=vol_desc,
        user_tags=m.user_tags,
    )

    return ret, new_vm_created
