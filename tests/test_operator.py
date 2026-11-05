import pytest
import yaml

from pg_spot_operator import constants, manifests, operator
from pg_spot_operator.cloud_impl.cloud_structs import InstanceTypeInfo
from pg_spot_operator.operator import (
    apply_short_life_time_instances_reordering,
    does_instance_type_fit_manifest_hw_reqs,
)
from tests.test_manifests import TEST_MANIFEST


@pytest.fixture(autouse=True)
def change_test_dir(request, monkeypatch):
    monkeypatch.chdir(request.fspath.dirname)


def test_exclude_prev_short_life_time_instances_leaving_at_least_one():

    resolved_instance_types: list[InstanceTypeInfo] = [
        InstanceTypeInfo(
            instance_type="i1",
            region="r1",
            arch="x86",
            availability_zone="az1",
            hourly_spot_price=1,
            max_eviction_rate=15,
        ),
        InstanceTypeInfo(
            instance_type="i1",
            region="r1",
            arch="x86",
            availability_zone="az2",
            hourly_spot_price=2,
            max_eviction_rate=10,
        ),
        InstanceTypeInfo(
            instance_type="i2",
            region="r1",
            arch="x86",
            availability_zone="az2",
            hourly_spot_price=3,
            max_eviction_rate=5,
        ),
    ]

    assert (
        len(
            apply_short_life_time_instances_reordering(
                resolved_instance_types, [("i1", "az1")]
            )
        )
        == 3
    )
    assert (
        apply_short_life_time_instances_reordering(
            resolved_instance_types, [("i1", "az1")]
        )[-1].instance_type
        == "i1"
    )
    # Ev. rate applied if whole shortlist had short lifetime
    assert (
        apply_short_life_time_instances_reordering(
            resolved_instance_types,
            [
                (x.instance_type, x.availability_zone)
                for x in resolved_instance_types
            ],
        )[0].instance_type
        == "i2"
    )
    # Order left in place if not short lifetime
    reordered = apply_short_life_time_instances_reordering(
        resolved_instance_types, [("i2", "az2")]
    )

    assert (reordered[0].instance_type, reordered[0].availability_zone) == (
        "i1",
        "az1",
    )
    assert (reordered[1].instance_type, reordered[1].availability_zone) == (
        "i1",
        "az2",
    )


def test_does_instance_type_info_fits_manifest_hw_reqs():
    iti1 = InstanceTypeInfo(
        instance_type="i1",
        region="r1",
        arch="x86",
        cpu=1,
    )
    iti2 = InstanceTypeInfo(
        instance_type="i2",
        region="r1",
        arch="x86",
        cpu=4,
        ram_mb=9000,
        instance_storage=1000,
    )
    m: manifests.InstanceManifest = manifests.load_manifest_from_string(
        TEST_MANIFEST
    )
    # vm:
    #  cpu_min: 2
    #  ram_min: 8
    # storage_min: 100
    # storage_type: local
    assert not does_instance_type_fit_manifest_hw_reqs(m, iti1)
    assert does_instance_type_fit_manifest_hw_reqs(m, iti2)


def test_action_install_os_pg_prereqs_constant():
    assert constants.ACTION_INSTALL_OS_PG_PREREQS == "install_os_pg_prereqs"


def test_action_install_os_extra_packages_constant():
    assert (
        constants.ACTION_INSTALL_OS_EXTRA_PACKAGES
        == "install_os_extra_packages"
    )


def test_install_os_pg_prereqs_playbook_contains_expected_roles():
    import os

    playbook_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "ansible",
        "v1",
        "install_os_pg_prereqs.yml",
    )
    with open(playbook_path) as f:
        data = yaml.safe_load(f)
    roles = [
        r.get("role") if isinstance(r, dict) else r
        for r in data[0].get("roles", [])
    ]
    assert "install_os_pg_prereqs" in roles


def test_install_os_extra_packages_playbook_contains_expected_role():
    import os

    playbook_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "ansible",
        "v1",
        "install_os_extra_packages.yml",
    )
    with open(playbook_path) as f:
        data = yaml.safe_load(f)
    roles = [
        r.get("role") if isinstance(r, dict) else r
        for r in data[0].get("roles", [])
    ]
    assert roles == ["install_os_extra_packages"]


def test_vm_only_runs_install_os_extra_packages_if_set(monkeypatch):
    m: manifests.InstanceManifest = manifests.load_manifest_from_string(
        TEST_MANIFEST
    )
    m.vm_only = True
    m.no_mount_disks = False
    m.os.extra_packages = ["some-package"]
    m.expiration_date = ""

    actions_called: list[str] = []

    def mock_register(destroy_base_path, manifest):
        manifest.uuid = "mock-uuid"
        manifest.manifest_snapshot_id = 1
        return None

    monkeypatch.setattr(
        operator, "register_or_update_manifest_in_cmdb", mock_register
    )
    monkeypatch.setattr(
        operator, "decrypt_and_set_aws_secrets_if_any", lambda manifest: None
    )
    monkeypatch.setattr(
        operator.cmdb,
        "get_last_successful_manifest_if_any",
        lambda uuid: None,
    )
    monkeypatch.setattr(
        operator.cmdb,
        "is_instance_ignore_listed",
        lambda name: False,
    )
    monkeypatch.setattr(
        operator,
        "ensure_vm",
        lambda manifest: (True, "mock-provider-id", "127.0.0.1"),
    )
    monkeypatch.setattr(
        operator, "check_ssh_ping_ok", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        operator,
        "run_action",
        lambda action, manifest: (actions_called.append(action), (True, {}))[
            1
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        operator.do_main_loop(cli_dry_run=True, cli_env_manifest=m)
    assert exc_info.value.code == 0
    assert actions_called == [
        constants.ACTION_MOUNT_DISKS,
        constants.ACTION_INSTALL_OS_EXTRA_PACKAGES,
    ]

    # When no_mount_disks is True, only install_os_extra_packages should run
    actions_called.clear()
    m.no_mount_disks = True
    with pytest.raises(SystemExit) as exc_info:
        operator.do_main_loop(cli_dry_run=True, cli_env_manifest=m)
    assert exc_info.value.code == 0
    assert actions_called == [constants.ACTION_INSTALL_OS_EXTRA_PACKAGES]
