import pytest

from pg_spot_operator import manifests
from pg_spot_operator.operator import apply_tuning_profile
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
