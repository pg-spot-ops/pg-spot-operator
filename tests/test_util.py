import tempfile

import pytest

from pg_spot_operator.util import (
    merge_action_output_params,
    decrypt_vault_secret,
    extract_region_from_az,
)


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
