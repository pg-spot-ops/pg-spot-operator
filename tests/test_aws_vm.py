import os.path
import datetime

from pg_spot_operator.cloud_impl import aws_vm


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


def test_get_ami_debian_amd():
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
