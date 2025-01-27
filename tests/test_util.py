import datetime
import tempfile

import pytest

from pg_spot_operator.util import (
    merge_action_output_params,
    decrypt_vault_secret,
    extract_region_from_az,
    get_aws_region_code_to_name_mapping,
    region_regex_to_actual_region_codes,
    space_pad_manifest,
    merge_user_and_tuned_non_conflicting_config_params,
    timestamp_to_human_readable_delta,
    extract_mtf_months_from_eviction_rate_group_label,
    pg_size_bytes,
)
from tests.test_manifests import TEST_MANIFEST_VAULT_SECRETS


def test_merge_action_output_params():
    assert merge_action_output_params(None, None) == {}
    merged = merge_action_output_params(
        {"out1": "a"}, {"out1": "b", "out2": "x"}
    )
    assert merged["out1"] == "a"
    assert len(merged) == 2


def test_decrypt_vault_secret():
    """Encrypted manually with:
    ansible-vault encrypt_string --vault-password-file ~/.pg-spot-operator/vault-passwordfile 'pgspotopsadmin' --name 'y'
    """
    secret = "pgspotops"
    with tempfile.NamedTemporaryFile() as tmpfile:
        tmpfile.write(secret.encode())
        tmpfile.flush()
        # print(tmpfile.name)
        encrypted = """$ANSIBLE_VAULT;1.1;AES256
30643364356334303739626534623937613733386535346661363166323138636537353666653262
3462353138393366393537643733666337353762363763620a333436343730373936343830646431
37363766353163666666613863363461656131646662653035336139383261643966323966633333
3532653838393935650a643666333361383465623463643563626337386235336166393966663733
3839"""
        assert decrypt_vault_secret(encrypted, tmpfile.name)


def test_extract_region_from_az():
    assert extract_region_from_az("eu-north-1b") == "eu-north-1"
    assert extract_region_from_az("us-west-2-lax-1a") == "us-west-2"
    with pytest.raises(Exception):
        extract_region_from_az("us-west-2-lax-1a-asdasda")


def test_get_aws_region_code_to_name_mapping():
    mapping = get_aws_region_code_to_name_mapping()
    assert mapping
    assert mapping["eu-north-1"] == "EU (Stockholm)"
    assert mapping["eu-north-1"] == "EU (Stockholm)"


def test_region_regex_to_actual_region_codes():
    # PS order or expected list matters
    test_values = [
        ("", sorted(list(get_aws_region_code_to_name_mapping().keys()))),
        ("eu-west", ["eu-west-1", "eu-west-2", "eu-west-3"]),
        ("london", ["eu-west-2"]),
        ("eu-west-1", ["eu-west-1"]),
        ("(us-east|ca-we)", ["ca-west-1", "us-east-1", "us-east-2"]),
        ("eu-(ce|no)", ["eu-central-1", "eu-central-2", "eu-north-1"]),
    ]
    for regex_input, expected in test_values:
        regs = region_regex_to_actual_region_codes(regex_input)
        assert regs == expected


def test_space_pad_manifest():
    padded = space_pad_manifest(TEST_MANIFEST_VAULT_SECRETS)
    assert (
        len(padded.splitlines())
        == len(TEST_MANIFEST_VAULT_SECRETS.splitlines()) - 1
    )  # +1 to account for removed ---
    assert padded.splitlines()[0].startswith("  ")


def test_merge_user_and_tuned_non_conflicting_config_params():
    """User config params override tuning output"""
    config_lines_tuned = {
        "param1": "100",
        "param2": "on",
        "collision": "tuningval",
    }
    config_lines_user = {"collision": "userval", "p4": "a"}
    merged = merge_user_and_tuned_non_conflicting_config_params(
        config_lines_tuned, config_lines_user
    )
    assert len(merged) == 4
    assert merged["collision"] == "userval"


def test_timestamp_str_to_human_readable_delta():
    hr = timestamp_to_human_readable_delta(
        datetime.datetime(2024, 10, 1), datetime.datetime(2024, 12, 1)
    )
    assert "month" in hr


def test_extract_mtf_months_from_eviction_rate_group_label():
    assert extract_mtf_months_from_eviction_rate_group_label("<5%") == 10
    assert extract_mtf_months_from_eviction_rate_group_label("10-15%") == 4
    assert extract_mtf_months_from_eviction_rate_group_label(">20%") == 0


def test_pg_size_bytes():
    # Test valid inputs
    assert pg_size_bytes("10 MB") == 10485760
    assert pg_size_bytes("1GB") == 1073741824
    assert pg_size_bytes("512 K") == 524288
    assert pg_size_bytes("100") == 100  # Default to bytes

    # Test with extra spaces
    assert pg_size_bytes("  2 TB ") == 2199023255552
    assert pg_size_bytes("3  PB") == 3377699720527872

    # Test lowercase units
    assert pg_size_bytes("5m") == 5242880

    # Test edge cases
    with pytest.raises(ValueError, match=r"Invalid size format: .*"):
        pg_size_bytes("invalid input")

    with pytest.raises(ValueError, match=r"Unknown size unit: .*"):
        pg_size_bytes("10 XB")
