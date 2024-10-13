#!/usr/bin/env python3

import argparse
import datetime
import logging
import os.path
import time

import boto3
import requests
from dateutil.parser import isoparse
from dateutil.tz import tzutc

EC2_METADATA_BASE_URL = "http://169.254.169.254/latest/meta-data"
SPOT_OPERATOR_ID_TAG = "pg-spot-operator-instance"

logger = logging.getLogger(__name__)

instance_name: str = ""
region: str = ""
instance_id: str = ""
access_key_id: str = ""
secret_access_key: str = ""
dry_run: bool = True


def str_to_bool(param: str) -> bool:
    if not param:
        return False
    if param.strip().lower() == "on":
        return True
    if param.strip().lower()[0] == "t":
        return True
    if param.strip().lower()[0] == "y":
        return True
    return False


def try_read_ec2_metadata(key_path: str) -> str:
    url = os.path.join(EC2_METADATA_BASE_URL, key_path)
    try:
        r = requests.get(url, timeout=1)
        if r.status_code != 200:
            raise Exception("Failed to read EC2 metadata url: " + url)
        return r.text
    except Exception:
        pass
    raise Exception("Failed to read EC2 metadata url: " + url)


def get_client(service: str, region: str):
    return boto3.client(
        service,
        region_name=region,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )


def get_operator_volumes_in_region(
    region: str, instance_name: str
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


def release_elastic_ip_addresses_if_any(
    region: str, spot_operator_instance_name: str
) -> None:
    client = get_client("ec2", region)

    filters = [
        {
            "Name": f"tag:{SPOT_OPERATOR_ID_TAG}",
            "Values": [spot_operator_instance_name],
        },
    ]
    resp = client.describe_addresses(Filters=filters)
    if resp and resp.get("Addresses") is not None:
        logger.info("Elastic Addresses found: %s", len(resp.get("Addresses")))
        if not dry_run:
            for addr_info in resp["Addresses"]:
                alloc_id = addr_info["AllocationId"]
                logger.info(
                    "Releasing Elastic Address with AllocationId %s ...",
                    alloc_id,
                )
                client.release_address(AllocationId=alloc_id)


def force_detach_volume_in_region(region: str, vol_id: str) -> None:
    client = get_client("ec2", region)
    resp = client.describe_volumes(VolumeIds=[vol_id])
    if resp and resp.get("Volumes"):
        if resp["Volumes"][0]["State"] != "available":
            logger.info("Force detaching VolumeId %s ...", vol_id)
            client.detach_volume(VolumeId=vol_id, Force=True)
            logger.info("Detach OK. Sleeping 10s ...")
            time.sleep(10)
    logger.info("Volume %s already detached", vol_id)


def delete_volume_in_region(
    region: str, vol_id: str, max_wait_seconds=300
) -> None:
    client = get_client("ec2", region)
    start_time = time.time()
    while time.time() < start_time + max_wait_seconds:
        try:
            logger.info("Deleting VolumeId %s ...", vol_id)
            client.delete_volume(VolumeId=vol_id)
            return
        except Exception:
            logger.exception(f"Failed to delete volume {vol_id}")
            time.sleep(30)
    raise Exception(f"Failed to delete volume {vol_id} in region {region}")


def force_detach_and_delete_volumes(
    region: str, spot_operator_instance_name: str
) -> None:
    vol_ids_and_sizes = get_operator_volumes_in_region(
        region, spot_operator_instance_name
    )
    logger.info("Volumes found: %s", vol_ids_and_sizes)
    if not dry_run and vol_ids_and_sizes:
        for vol_id, size in vol_ids_and_sizes:
            force_detach_volume_in_region(region, vol_id)
            delete_volume_in_region(region, vol_id)


def self_terminate_instance(region: str, instance_id: str):
    client = get_client("ec2", region)
    logger.info("Terminating instance %s ...", instance_id)
    client.terminate_instances(InstanceIds=[instance_id], DryRun=dry_run)


def is_expiration_date_passed(expiration_date: str) -> bool:
    if expiration_date.lower() == "now":
        return True

    dtt = isoparse(expiration_date)
    if not dtt.tzinfo:
        dtt = dtt.replace(tzinfo=tzutc())
    if dtt <= datetime.datetime.now(datetime.timezone.utc):
        return True
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Terminates a pg-spot-operator instance and related resources",
        add_help=True,
    )

    parser.add_argument(
        "instance_name",
        metavar="INSTANCE_NAME",
        help="PG Spot Operator instance name",
    )
    parser.add_argument(
        "expiration_date",
        metavar="EXPIRATION_DATE",
        help="ISO 8601 datetime a la '2024-12-22 00:00+03' or 'now'",
    )
    parser.add_argument(
        "--dry-run",
        metavar="DRY_RUN",
        default=True,
        type=str_to_bool,
        help="Set to no/false to actually destroy",
    )
    parser.add_argument(
        "--region",
        metavar="REGION",
        help="Self discovered from EC2 metadata if not set",
    )
    parser.add_argument(
        "--instance-id",
        metavar="INSTANCE_ID",
        help="Self discovered from EC2 metadata if not set",
    )
    parser.add_argument(
        "--access-key-id",
        metavar="ACCESS_KEY_ID",
        help="If not set assume .aws/credentials set",
    )
    parser.add_argument(
        "--secret-access-key",
        metavar="SECRET_ACCESS_KEY",
        help="If not set assume .aws/credentials set",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        metavar="VERBOSE",
        default=False,
        type=str_to_bool,
        help="More chat",
    )

    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )
    logger.debug("Input args: %s", args)

    instance_name = args.instance_name
    region = args.region
    instance_id = args.instance_id
    access_key_id = args.access_key_id
    secret_access_key = args.secret_access_key
    dry_run = args.dry_run

    if not is_expiration_date_passed(args.expiration_date):
        logger.debug("Expiration date not yet arrived. Exit")
        exit(0)

    if not access_key_id and not os.path.exists(
        os.path.expanduser("~/.aws/credentials")
    ):
        logger.error(
            "Expecting ~/.aws/credentials to be set when AWS access keys not specified directly"
        )
        exit(1)

    logger.info(
        "Starting %s teardown for instance %s ...",
        "DRY-RUN" if args.dry_run else "ACTUAL",
        args.instance_name,
    )

    if not region:
        region = try_read_ec2_metadata("placement/region")
        logger.info("Detected EC2 region: %s", region)
    if not instance_id:
        instance_id = try_read_ec2_metadata("instance-id")
        logger.info("Detected EC2 instance-id: %s", instance_id)

    force_detach_and_delete_volumes(region, instance_name)

    release_elastic_ip_addresses_if_any(region, instance_name)

    self_terminate_instance(region, instance_id)
