import pytest

from pg_spot_operator import manifests
from pg_spot_operator.cloud_impl.cloud_structs import InstanceTypeInfo
from pg_spot_operator.operator import (
    apply_tuning_profile,
    exclude_prev_short_life_time_instances_leaving_at_least_one,
)
from .test_manifests import TEST_MANIFEST


@pytest.fixture(autouse=True)
def change_test_dir(request, monkeypatch):
    monkeypatch.chdir(request.fspath.dirname)


def test_apply_tuning_profile():
    m: manifests.InstanceManifest = manifests.load_manifest_from_string(
        TEST_MANIFEST
    )
    assert m
    tuning_lines = apply_tuning_profile(
        m, tuning_profiles_path="../tuning_profiles"
    )
    assert len(tuning_lines) > 5


def test_exclude_prev_short_life_time_instances_leaving_at_least_one():
    resolved_instance_types: list[InstanceTypeInfo] = [
        InstanceTypeInfo(
            instance_type="i1",
            region="r1",
            arch="x86",
            availability_zone="az1",
            hourly_spot_price=1,
        ),
        InstanceTypeInfo(
            instance_type="i1",
            region="r1",
            arch="x86",
            availability_zone="az2",
            hourly_spot_price=2,
        ),
        InstanceTypeInfo(
            instance_type="i2",
            region="r1",
            arch="x86",
            availability_zone="az2",
            hourly_spot_price=3,
        ),
    ]

    assert (
        len(
            exclude_prev_short_life_time_instances_leaving_at_least_one(
                resolved_instance_types, [("i1", "az1")]
            )
        )
        == 2
    )
    assert (
        len(
            exclude_prev_short_life_time_instances_leaving_at_least_one(
                resolved_instance_types,
                [
                    (x.instance_type, x.availability_zone)
                    for x in resolved_instance_types
                ],
            )
        )
        == 1
    )
    assert (
        exclude_prev_short_life_time_instances_leaving_at_least_one(
            resolved_instance_types,
            [
                (x.instance_type, x.availability_zone)
                for x in resolved_instance_types
            ],
        )[0].instance_type
        == "i1"
    )
