import os.path
import datetime
import unittest

import yaml

from pg_spot_operator import manifests
from pg_spot_operator.cloud_impl import aws_vm
from pg_spot_operator.cloud_impl.aws_vm import (
    ensure_spot_vm,
    compile_cloud_init_user_data_config,
)

TEST_MANIFEST = """
---
api_version: v1
kind: pg_spot_operator_instance
cloud: aws
region: eu-north-1
instance_name: test123
vm:
  cpu_min: 2
  storage_type: local
"""


def test_get_ami_debian_amd():
    """Assumes local AWS CLI setup"""
    if not os.path.exists(os.path.expanduser("~/.aws/config")):
        return

    ami, details = aws_vm.get_latest_ami_for_region_arch(
        region="eu-north-1", architecture="amd64"
    )
    # print('details', details)
    assert ami.startswith("ami")
    cd = datetime.datetime.fromisoformat(details["CreationDate"].rstrip("Z"))
    assert cd > datetime.datetime.now() - datetime.timedelta(days=365)
    assert details["Architecture"] == "x86_64"


def test_get_ami_debian_arm():
    """Assumes local AWS CLI setup"""
    if not os.path.exists(os.path.expanduser("~/.aws/config")):
        return

    ami, details = aws_vm.get_latest_ami_for_region_arch(
        region="eu-north-1", architecture="arm64"
    )
    assert ami.startswith("ami")
    cd = datetime.datetime.fromisoformat(details["CreationDate"].rstrip("Z"))
    assert cd > datetime.datetime.now() - datetime.timedelta(days=365)
    assert details["Architecture"] == "arm64"


@unittest.SkipTest
def test_ensure_spot_vm_local_storage():
    m: manifests.InstanceManifest = manifests.load_manifest_from_string(
        TEST_MANIFEST
    )
    assert m
    assert m.cloud == "aws"
    vm, created = ensure_spot_vm(m)
    print("vm", vm)
    assert created
    assert vm.ip_public
    assert not vm.volume_id


def test_compile_cloud_init_user_data_config():
    """https://cloudinit.readthedocs.io/en/22.2.2/topics/examples.html#yaml-examples"""
    user_data = compile_cloud_init_user_data_config(
        "reg",
        "lu",
        "~/.ssh/dummypath",
        ["key1", "key2"],
        "",
    )
    assert user_data
    d = yaml.safe_load(user_data)
    # print(d)
    assert len(d["users"][0]["ssh-authorized-keys"]) == 2
