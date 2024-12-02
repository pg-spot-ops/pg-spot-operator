import tempfile

from pg_spot_operator import manifests


TEST_MANIFEST = """
---
api_version: v1
kind: pg_spot_operator_instance
cloud: aws
region: eu-west-1
#availability_zone:
instance_name: hello
#vault_password_file:
expiration_date: now
postgres:
  version: 16
  tuning_profile: oltp  # builtins: oltp | warehouse | web | mixed  
  admin_user: dev
  admin_password: dev
  admin_is_superuser: true  # Assign all safe built-in roles + make DB owner
  config_lines:  # Possibly overrides any tuned values
    pg_stat_statements.max: 1000
    pg_stat_statements.track_utility: off
  pg_hba_lines:
    - "hostssl all all 0.0.0.0/0 scram-sha-256"      
  initdb_opts:
    - data-checksums
    - "locale-provider: icu"
    - "icu-locale: en"
    - "locale: en_US.utf8"
vm:
  cpu_min: 2
  ram_min: 8
  sku:  # Cpu etc will be ignored then
  storage_min: 100
  storage_type: local  # local | network
  storage_speed_class: ssd  # hdd | ssd | nvme. Not guaranteed to be honoured
#  volume_type:  # e.g. gp3
#  volume_size_min:  # 100
#  volume_iops:  # For provisioned / paid IOPS, EBS gp3 default is 3000
#  volume_throughput:  # MBs. For provisioned / paid throughput. EBS gp3 default is 125
os:
  extra_packages: []
user_tags:
  app: backend
  team: hackers
"""

TEST_MANIFEST_EXPIRATION_DATE = """
---
api_version: v1
kind: pg_spot_operator_instance
cloud: aws
region: eu-west-1
instance_name: hello
expiration_date: "2025-02-08 09-0100"
"""

TEST_MANIFEST_VAULT_SECRETS = """
---
api_version: v1
kind: pg_spot_operator_instance
cloud: aws
region: eu-west-1
instance_name: hello
postgres:
  admin_password: !vault |
    $ANSIBLE_VAULT;1.1;AES256
    30643364356334303739626534623937613733386535346661363166323138636537353666653262
    3462353138393366393537643733666337353762363763620a333436343730373936343830646431
    37363766353163666666613863363461656131646662653035336139383261643966323966633333
    3532653838393935650a643666333361383465623463643563626337386235336166393966663733
    3839
"""


TEST_MANIFEST_INSTANCE_TYPES = """
---
api_version: v1
kind: pg_spot_operator_instance
cloud: aws
region: eu-west-1
instance_name: hello
expiration_date: "2025-02-08 09-0100"
vm:
  instance_types:
    - i3.large
    - i3.xlarge
"""


def test_parse_manifest():
    m: manifests.InstanceManifest = manifests.load_manifest_from_string(
        TEST_MANIFEST
    )
    assert m
    assert m.cloud == "aws"
    assert m.instance_name == "hello"
    assert m.postgres.admin_is_superuser
    assert m.is_expired()
    m.expiration_date = "2099-01-01"
    assert not m.is_expired()


def test_fill_in_defaults():
    m: manifests.InstanceManifest = manifests.load_manifest_from_string(
        TEST_MANIFEST_EXPIRATION_DATE
    )
    assert m
    m.fill_in_defaults()
    assert m.expiration_date and " " not in m.expiration_date


def test_decrypt_vault_secrets():
    """Encrypted manually with:
    echo -n "pgspotops" > /tmp/vault-secret
    ansible-vault encrypt_string --vault-password-file /tmp/vault-secret 'pgspotopsadmin'
    """
    secret = "pgspotops"
    with tempfile.NamedTemporaryFile() as tmpfile:
        tmpfile.write(secret.encode())
        tmpfile.flush()
        # print(tmpfile.name)
        m: manifests.InstanceManifest = manifests.load_manifest_from_string(
            TEST_MANIFEST_VAULT_SECRETS
        )
        assert m.postgres.admin_password
        assert m.postgres.admin_password.startswith("$ANSIBLE_VAULT")
        m.vault_password_file = tmpfile.name
        secrets_found, decrypted = m.decrypt_secrets_if_any()
        assert secrets_found > 0 and decrypted == 1


def test_multi_instance():
    m: manifests.InstanceManifest = manifests.load_manifest_from_string(
        TEST_MANIFEST_INSTANCE_TYPES
    )
    assert m
    assert len(m.vm.instance_types) == 2
