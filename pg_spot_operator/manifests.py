import datetime
import logging
from dataclasses import field
from typing import Any

import deepdiff
import yaml
from dateutil.parser import isoparse, parse
from dateutil.tz import tzutc
from pydantic import BaseModel, ValidationError, model_validator
from typing_extensions import Self

from pg_spot_operator.constants import (
    CLOUD_AWS,
    DEFAULT_POSTGRES_MAJOR_VER,
    SPOT_OPERATOR_EXPIRES_TAG,
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
    initdb_opts: list[str] | None = field(default_factory=list)
    admin_user: str | None = None
    admin_user_password: str | None = None
    password_version: int | None = None
    admin_user_password_file: str | None = None
    admin_is_real_superuser: bool | None = None
    ensure_app_dbname: str | None = None


class SectionVm(BaseModel):
    cpu_architecture: str = ""
    allow_burstable: bool = True
    detailed_monitoring: bool = False  # Has extra cost
    cpu_min: int = 0
    cpu_max: int = 0
    ram_min: int = 0
    storage_min: int = 0
    storage_type: str = "network"
    storage_speed_class: str = "ssd"
    instance_type: str = ""  # Min CPU etc. will be ignored then
    volume_type: str = "gp3"
    volume_iops: int = 0
    volume_throughput: int = 0
    unattended_security_upgrades: bool = (
        True  # Might result in nightly restarts
    )
    kernel_tuning: bool = True  # Basic memory over-commit tuning only for now


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
    access_key_id: str = ""
    secret_access_key: str = ""
    security_group_ids: list[str] = field(default_factory=list)
    subnet_id: str = ""
    profile_name: str = ""
    key_pair_name: str = ""


class SectionPgConfig(BaseModel):
    tuning_profile: str = "default"
    extensions: list[str] = field(default_factory=list)
    extra_os_packages: list[str] = field(default_factory=list)
    ensure_shared_preload_libraries: list[str] = field(default_factory=list)
    extra_config_lines: list[str] = field(default_factory=list)


class InstanceManifest(BaseModel):
    # *Internal engine usage fields*
    original_manifest: str = ""
    manifest_snapshot_id: int = 0
    uuid: str | None = None  # CMDB ID
    session_vars: dict = field(default_factory=dict)  #
    # *Top-level instance fields*
    # Required fields
    api_version: str
    kind: str
    cloud: str
    region: str
    instance_name: str
    # Optional fields
    postgres_version: int = DEFAULT_POSTGRES_MAJOR_VER
    assign_public_ip: bool = True
    floating_public_ip: bool = (
        True  # Has only relevance if assign_public_ip set
    )
    description: str = ""
    availability_zone: str = ""
    user_tags: dict = field(default_factory=dict)
    vault_password_file: str = ""
    expiration_date: str = ""  # now | '2024-06-11 10:40'
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
            "session_vars",
        }

    def is_expired(self) -> bool:
        """Checks if passed expiration_date"""
        if not self.expiration_date:
            return False
        if self.expiration_date.lower() == "now":
            return True
        try:
            dtt = parse(self.expiration_date)
            if not dtt.tzinfo:
                dtt = dtt.replace(tzinfo=tzutc())
            if dtt < datetime.datetime.utcnow():
                return True
        except Exception:
            logger.exception(
                f"Failed to parse expiration_date attribute for manifest {self.uuid}"
            )
        return False

    def fill_in_defaults(self):
        self.user_tags[SPOT_OPERATOR_ID_TAG] = self.instance_name
        if (
            self.expiration_date
            and self.expiration_date.lower().strip() != "now"
        ):
            self.expiration_date = self.expiration_date.replace(" ", "T")
            self.user_tags[SPOT_OPERATOR_EXPIRES_TAG] = self.expiration_date

    def decrypt_secrets_if_any(self) -> tuple[int, int]:
        """Could also be made generic somehow - a la loop over model_dump but need it only for the Postgres password for now
        Returns number of secrets found / decrypted
        """
        secrets_found = decrypted = 0
        if (
            self.pg.admin_user_password
            and self.pg.admin_user_password.startswith("$ANSIBLE_VAULT")
        ):
            secrets_found += 1
            if (
                not self.vault_password_file
                and not default_vault_password_file
            ):
                logger.warning(
                    "Could not decrypt admin_user_password as no vault_password_file set"
                )
                return secrets_found, decrypted
            try:
                decrypted_secret = decrypt_vault_secret(
                    self.pg.admin_user_password,
                    self.vault_password_file or default_vault_password_file,
                )
                if decrypted_secret:
                    self.pg.admin_user_password = decrypted_secret
                    decrypted += 1
            except Exception:
                logger.exception("Failed to decrypt pg.admin_user_password")
        return secrets_found, decrypted

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
            raise ValueError("Only aws cloud supported for now")
        return self

    @model_validator(mode="after")
    def check_valid_expiration_date(self) -> Self:
        if self.expiration_date and self.expiration_date != "now":
            try:
                isoparse(self.expiration_date)
            except Exception:
                raise ValueError(
                    "Failed to parse expiration_date, expecting an ISO-8601 datetime string, e.g. 2025-10-22T00:00+03"
                )
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
