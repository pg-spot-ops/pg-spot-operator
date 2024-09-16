import pytest
from pydantic import ValidationError

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
destroy_target_time_utc: now
pg:
  major_ver: 16
  admin_user: dev
  admin_password: dev
  admin_is_real_superuser: true  # Assign all safe built-in roles + make DB owner
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
  volume_type:  # e.g. gp3
  volume_size_min:  # 100
  volume_iops:  # For provisioned / paid IOPS, EBS gp3 default is 3000
  volume_throughput:  # MBs. For provisioned / paid throughput. EBS gp3 default is 125
pg_config:
  tuning_profile: oltp  # builtins: oltp | warehouse | web | mixed
  extension_packages:
    - cron  # Engine will look for and install the postgresql-$major_ver-cron package
            # Still need to add to ensure_shared_preload_libraries though and create the extension in SQL!
  ensure_shared_preload_libraries:
    - pg_stat_statements
    - cron
  extra_config_lines:  # Possibly overrides any tuned values
    - "pg_stat_statements.max = 1000"
    - "pg_stat_statements.track_utility = off"
access:
  pg_hba:
    - "hostssl all all 0.0.0.0/0 scram-sha-256"
user_tags:
  app: backend
  team: hackers
"""


def test_parse_manifest():
    m: manifests.InstanceManifest = manifests.load_manifest_from_string(
        TEST_MANIFEST
    )
    assert m
    assert m.cloud == "aws"
    assert m.instance_name == "hello"
    assert m.pg.admin_is_real_superuser
    assert m.is_expired()
    m.destroy_target_time_utc = "2099-01-01"
    assert not m.is_expired()
