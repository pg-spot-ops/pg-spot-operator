import pytest

from pg_spot_operator import manifests
from pg_spot_operator.cloud_impl.cloud_structs import InstanceTypeInfo
from pg_spot_operator.operator import (
    apply_short_life_time_instances_reordering,
    does_instance_type_fit_manifest_hw_reqs,
    dry_run,
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
