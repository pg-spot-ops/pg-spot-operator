from pg_spot_operator import manifests
from pg_spot_operator.operator import get_tuning_inputs_from_manifest_hw_reqs
from pg_spot_operator.pgtuner import apply_postgres_tuning
from tests.test_manifests import TEST_MANIFEST


def test_apply_tuning_profile():
    m: manifests.InstanceManifest = manifests.load_manifest_from_string(
        TEST_MANIFEST
    )
    assert m

    tuning_input = get_tuning_inputs_from_manifest_hw_reqs(m)

    tuned_config_params = apply_postgres_tuning(tuning_input, "default")

    assert len(tuned_config_params) > 5
    assert "shared_buffers" in tuned_config_params
    assert tuned_config_params["shared_buffers"]
