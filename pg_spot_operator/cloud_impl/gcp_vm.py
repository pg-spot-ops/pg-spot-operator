import logging

import googleapiclient.discovery
from google.cloud import compute_v1

logger = logging.getLogger(__name__)

logging.getLogger("google").setLevel(logging.ERROR)


def get_latest_debian_image() -> str:  # TODO Arm64 support
    compute = googleapiclient.discovery.build("compute", "v1")

    image_response = (
        compute.images()
        .getFromFamily(project="debian-cloud", family="debian-12")
        .execute()
    )
    return image_response["selfLink"]


def create_instance(
    project: str,
    zone: str,
    machine_type: str,
    instance_name: str,
) -> str:
    """Creates an instance in the specified zone"""

    client = compute_v1.InstancesClient()

    instance = compute_v1.Instance(
        name=instance_name,
        zone=zone,
        machine_type=f"zones/{zone}/machineTypes/{machine_type}",
        disks=[
            compute_v1.AttachedDisk(
                boot=True,
                auto_delete=True,
                initialize_params=compute_v1.AttachedDiskInitializeParams(
                    source_image=get_latest_debian_image(),
                ),
            )
        ],
        network_interfaces=[
            compute_v1.NetworkInterface(
                name="global/networks/default",
            )
        ],
    )

    response = client.insert(
        project=project, zone=zone, instance_resource=instance
    )
    print(response)
    return "OK"


def delete_instance(
    project: str,
    zone: str,
    name: str,
) -> str:
    """Deletes an instance"""
    client = compute_v1.InstancesClient()
    client.delete(project=project, zone=zone, instance=name)


if __name__ == "__main__":
    create_instance("kaarel-devel", "europe-north1-a", "e2-micro", "sadas")
