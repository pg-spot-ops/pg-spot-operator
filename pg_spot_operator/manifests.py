import datetime
import logging
from dataclasses import field
from typing import Any

import deepdiff
import yaml
from dateutil.parser import parse
from dateutil.tz import tzutc
from pydantic import BaseModel, ValidationError, model_validator
from typing_extensions import Self

from pg_spot_operator.constants import (
    CLOUD_AWS,
    DEFAULT_POSTGRES_MAJOR_VER,
    SPOT_OPERATOR_ID_TAG,
)
from pg_spot_operator.util import decrypt_vault_secret

logger = logging.getLogger(__name__)

default_vault_password_file: str = ""


def ignore(loader, tag, node):
    """Work around custom tags (!vault) throwing an error a la https://github.com/yaml/pyyaml/issues/266"""
    classname = node.__class__.__name__
    if classname == "SequenceNode":
        resolved = loader.construct_sequence(node)
    elif classname == "MappingNode":
        resolved = loader.construct_mapping(node)
    else:
        resolved = loader.construct_scalar(node)
    return resolved


yaml.add_multi_constructor("!", ignore, Loader=yaml.SafeLoader)


class SectionPg(BaseModel):
    major_ver: int = DEFAULT_POSTGRES_MAJOR_VER
    initdb_opts: list[str] | None = field(default_factory=list)
    admin_user: str | None = None
    admin_user_password: str | None = None
    password_version: int | None = None
    admin_user_password_file: str | None = None
    admin_is_real_superuser: bool | None = None
    ensure_app_dbname: str | None = None


class SectionVm(BaseModel):
    architecture: str | None = None
    allow_burstable: bool | None = None
    assign_public_ip_address: bool | None = None
    floating_public_ip: bool | None = None
    detailed_monitoring: bool | None = None
    cpu_min: int | None = None
    cpu_max: int | None = None
    ram_min: int | None = None
    storage_min: int | None = None
    storage_type: str | None = None  # local | network
    storage_speed_class: str | None = None
    instance_type: str | None = None  # Min CPU etc. will be ignored then
    volume_type: str | None = None
    volume_iops: int | None = None
    volume_throughput: int | None = None
    unattended_security_upgrades: bool | None = (
        None  # Might result in nightly restarts
    )
    kernel_tuning: bool | None = (
        None  # Basic memory over-commit tuning only for now
    )


class SubSectionPgbackrest(BaseModel):
    global_settings: dict = field(default_factory=dict)
    archive_push_overrides: dict = field(default_factory=dict)
    backup_overrides: dict = field(default_factory=dict)
    restore_overrides: dict = field(default_factory=dict)


class SectionBackup(BaseModel):
    type: str = "none"
    wal_archiving_max_interval: str = ""
    retention_days: int = 1
    schedule_full: str = ""
    schedule_diff: str = ""
    encryption: bool = False
    cipher_password: str = ""
    cipher_password_file: str = ""
    s3_key: str = ""
    s3_key_file: str = ""
    s3_key_secret: str = ""
    s3_key_secret_file: str = ""
    pgbackrest: SubSectionPgbackrest = field(
        default_factory=SubSectionPgbackrest
    )


class SectionAccess(BaseModel):
    extra_ssh_pub_keys: list[str] = field(default_factory=list)
    extra_ssh_pub_key_paths: list[str] = field(default_factory=list)
    pg_hba: list[str] = field(default_factory=list)


class SectionAws(BaseModel):
    security_group_ids: list[str] = field(default_factory=list)
    subnet_id: str = ""
    profile_name: str = ""
    key_pair_name: str = ""


class SectionPgConfig(BaseModel):
    tuning_profile: str = ""
    extensions: list[str] = field(default_factory=list)
    extra_os_packages: list[str] = field(default_factory=list)
    ensure_shared_preload_libraries: list[str] = field(default_factory=list)
    extra_config_lines: list[str] = field(default_factory=list)


class InstanceManifest(BaseModel):
    # *Internal engine usage fields*
    original_manifest: str = ""
    manifest_snapshot_id: int = 0
    uuid: str = ""
    session_invars: dict = field(default_factory=dict)
    session_outvars: dict = field(default_factory=dict)
    # *Top-level instance fields*
    # Required fields
    api_version: str
    kind: str
    cloud: str
    region: str
    instance_name: str
    # Optional fields
    description: str = ""
    availability_zone: str = ""
    user_tags: dict = field(default_factory=dict)
    vault_password_file: str = ""
    destroy_target_time_utc: str = ""  # now | '2024-06-11 10:40'
    destroy_backups: bool = True
    # *Sections*
    pg: SectionPg = field(default_factory=SectionPg)
    vm: SectionVm = field(default_factory=SectionVm)
    backup: SectionBackup = field(default_factory=SectionBackup)
    pg_config: SectionPgConfig = field(default_factory=SectionPgConfig)
    access: SectionAccess = field(default_factory=SectionAccess)
    aws: SectionAws = field(default_factory=SectionAws)

    @staticmethod
    def get_internal_usage_attributes() -> set:
        return {
            "manifest_snapshot_id",
            "uuid",
            "original_manifest",
            "session_invars",
            "session_outvars",
        }

    def is_expired(self) -> bool:
        """Checks if passed destroy_target_time_utc"""
        if not self.destroy_target_time_utc:
            return False
        if self.destroy_target_time_utc.lower() == "now":
            return True
        try:
            dtt = parse(self.destroy_target_time_utc)
            if not dtt.tzinfo:
                dtt = dtt.replace(tzinfo=tzutc())
            if dtt < datetime.datetime.utcnow():
                return True
        except Exception:
            logger.exception(
                f"Failed to parse destroy_target_time_utc attribute for manifest {self.uuid}"
            )
        return False

    def fill_in_defaults(self):
        self.user_tags[SPOT_OPERATOR_ID_TAG] = self.instance_name

    def decrypt_secrets_if_any(self) -> None:
        """Could also be made generic - a la loop over model_dump but need it only for the Postgres password for now"""
        if not self.vault_password_file and not default_vault_password_file:
            if (
                self.pg.admin_user_password
                and self.pg.admin_user_password.startswith("$ANSIBLE_VAULT")
            ):
                logger.warning(
                    "Could not decrypt admin_user_password as no vault_password_file set"
                )
            return
        if (
            self.pg.admin_user_password
            and self.pg.admin_user_password.startswith("$ANSIBLE_VAULT")
        ):
            self.pg.admin_user_password = decrypt_vault_secret(
                self.pg.admin_user_password,
                self.vault_password_file or default_vault_password_file,
            )

    def diff_manifests(
        self, prev_manifest, original_manifests_only: bool = False
    ) -> dict:
        if not prev_manifest:
            return {}
        cur_model = self
        prev_model = prev_manifest
        if original_manifests_only:
            cur_model = load_manifest_from_string(self.original_manifest)

            prev_model = load_manifest_from_string(
                prev_manifest.original_manifest
            )
        cur_dict = cur_model.dict(
            exclude=self.get_internal_usage_attributes(),
        )
        prev_dict = prev_model.dict(
            exclude=self.get_internal_usage_attributes(),
        )
        return deepdiff.diff.DeepDiff(prev_dict, cur_dict).to_dict()

    @model_validator(mode="after")
    def check_aws(self) -> Self:
        if self.cloud != CLOUD_AWS:
            return self
        return self


def load_manifest_from_string(manifest_yaml_str: Any) -> InstanceManifest:
    m = yaml.safe_load(manifest_yaml_str)
    return InstanceManifest(**m)


def try_load_manifest_from_string(
    manifest_yaml_str: Any,
) -> InstanceManifest | None:
    try:
        m = yaml.safe_load(manifest_yaml_str)
        mf = InstanceManifest(**m)
        mf.original_manifest = manifest_yaml_str
        return mf
    except ValidationError as e:
        logger.error(
            "Failed to load user manifest from string: %s", manifest_yaml_str
        )
        logger.error(str(e))
    except Exception:
        return None
    return None