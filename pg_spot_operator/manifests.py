import datetime
import logging
import os.path
import re
from dataclasses import field
from typing import Any

import deepdiff
import yaml
from dateutil.parser import isoparse
from dateutil.tz import tzutc
from pydantic import BaseModel, ValidationError, model_validator
from typing_extensions import Self

from pg_spot_operator.constants import (
    BACKUP_TYPE_PGBACKREST,
    CLOUD_AWS,
    DEFAULT_POSTGRES_MAJOR_VER,
    SPOT_OPERATOR_EXPIRES_TAG,
    SPOT_OPERATOR_ID_TAG,
)
from pg_spot_operator.util import (
    decrypt_vault_secret,
    extract_region_from_az,
    read_file,
)

logger = logging.getLogger(__name__)

default_vault_password_file: str = ""
default_setup_finished_callback: str = ""


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


class SectionAnsible(BaseModel):
    private_key: str = ""


class SectionPostgresql(BaseModel):
    version: int = DEFAULT_POSTGRES_MAJOR_VER
    tuning_profile: str = "default"
    admin_user: str | None = None
    admin_user_password: str | None = None
    admin_is_superuser: bool = False
    app_db_name: str | None = None
    config_lines: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    pg_hba_lines: list[str] = field(default_factory=list)
    initdb_opts: list[str] = field(default_factory=list)


class SectionVm(BaseModel):
    cpu_architecture: str = ""
    allow_burstable: bool = (
        False  # T-class instances tend to get killed more often, thus exclude by default
    )
    detailed_monitoring: bool = False  # Has extra cost
    cpu_min: int = 0
    cpu_max: int = 0
    ram_min: int = 0
    storage_min: int = 0
    storage_type: str = "network"
    storage_speed_class: str = "ssd"
    instance_types: list[str] = field(
        default_factory=list
    )  # Min CPU etc. will be ignored then
    instance_selection_strategy: str = "cheapest"
    volume_type: str = "gp3"
    volume_iops: int = 0
    volume_throughput: int = 0
    host: str = ""  # Skip VM creation, use provided host for Postgres setup
    login_user: str = (
        ""  # Skip VM creation, use provided login user for Postgres setup
    )


class SectionOs(BaseModel):
    unattended_security_upgrades: bool = (
        True  # Might result in nightly restarts
    )
    kernel_tuning: bool = True  # Basic memory over-commit tuning only for now
    extra_packages: list[str] = field(default_factory=list)
    ssh_pub_keys: list[str] = field(default_factory=list)
    ssh_pub_key_paths: list[str] = field(default_factory=list)


class SubSectionPgbackrest(BaseModel):
    global_settings: dict = field(default_factory=dict)
    archive_push_overrides: dict = field(default_factory=dict)
    backup_overrides: dict = field(default_factory=dict)
    restore_overrides: dict = field(default_factory=dict)


class SectionBackup(BaseModel):
    type: str = "none"
    destroy_backups: bool = True
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
    s3_bucket: str = ""
    pgbackrest: SubSectionPgbackrest = field(
        default_factory=SubSectionPgbackrest
    )


class SectionAws(BaseModel):
    access_key_id: str = ""
    secret_access_key: str = ""
    security_group_ids: list[str] = field(default_factory=list)
    vpc_id: str = ""
    subnet_id: str = ""
    profile_name: str = ""
    key_pair_name: str = ""
    self_terminate_access_key_id: str = ""
    self_terminate_secret_access_key: str = ""


class SubSectionMonitoringPrometheus(BaseModel):
    enabled: bool = False
    externally_accessible: bool = False


class SubSectionMonitoringGrafana(BaseModel):
    enabled: bool = False
    externally_accessible: bool = True
    admin_user: str = "pgspotops"
    admin_password: str = ""
    anonymous_access: bool = True
    protocol: str = "https"


class SectionMonitoring(BaseModel):
    prometheus_node_exporter: SubSectionMonitoringPrometheus = field(
        default_factory=SubSectionMonitoringPrometheus
    )
    grafana: SubSectionMonitoringGrafana = field(
        default_factory=SubSectionMonitoringGrafana
    )


class InstanceManifest(BaseModel):
    # *Internal engine usage fields*
    original_manifest: str = ""
    manifest_snapshot_id: int = 0
    uuid: str | None = None  # CMDB ID
    session_vars: dict = field(default_factory=dict)
    # *Top-level instance fields*
    # Required fields
    api_version: str
    kind: str
    cloud: str
    region: str = ""
    instance_name: str
    # Optional fields
    assign_public_ip: bool = True
    floating_ips: bool = (
        True  # If False NIC resources can be left hanging if not cleaned up properly
    )
    description: str = ""
    availability_zone: str = ""
    user_tags: dict = field(default_factory=dict)
    vault_password_file: str = ""
    setup_finished_callback: str = ""  # An executable passed to Ansible
    expiration_date: str = ""  # now | '2024-06-11 10:40'
    self_terminate: bool = False
    is_paused: bool = False
    # *Sections*
    postgresql: SectionPostgresql = field(default_factory=SectionPostgresql)
    vm: SectionVm = field(default_factory=SectionVm)
    backup: SectionBackup = field(default_factory=SectionBackup)
    os: SectionOs = field(default_factory=SectionOs)
    aws: SectionAws = field(default_factory=SectionAws)
    monitoring: SectionMonitoring = field(default_factory=SectionMonitoring)
    ansible: SectionAnsible = field(default_factory=SectionAnsible)

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
            dtt = isoparse(self.expiration_date)
            if not dtt.tzinfo:
                dtt = dtt.replace(tzinfo=tzutc())
            if dtt < datetime.datetime.now(datetime.timezone.utc):
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
        if self.availability_zone and not self.region:
            self.region = self.session_vars["region"] = extract_region_from_az(
                self.availability_zone
            )
        if (
            not self.setup_finished_callback
            and default_setup_finished_callback
        ):
            self.setup_finished_callback = default_setup_finished_callback
        if (
            self.setup_finished_callback
            and "~" in self.setup_finished_callback
        ):
            self.setup_finished_callback = os.path.expanduser(
                self.setup_finished_callback
            )
        if (
            self.backup.type == BACKUP_TYPE_PGBACKREST
        ):  # Required to create the bucket
            if not self.backup.s3_key and self.backup.s3_key_file:
                self.backup.s3_key = read_file(self.backup.s3_key_file)
            if (
                not self.backup.s3_key_secret
                and self.backup.s3_key_secret_file
            ):
                self.backup.s3_key_secret = read_file(
                    self.backup.s3_key_secret_file
                )
        if (
            self.monitoring.grafana.admin_user
            and not self.monitoring.grafana.admin_password
        ):
            self.monitoring.grafana.admin_password = self.session_vars[
                "monitoring"
            ] = {"grafana": {"admin_password": self.instance_name}}

    def decrypt_secrets_if_any(self) -> tuple[int, int]:
        """Could also be made generic somehow - a la loop over model_dump but need it only for the Postgres password for now
        Returns number of secrets found / decrypted
        """
        secrets_found = decrypted = 0
        # There are also some secret backup section fields also but they're touched only in Ansible
        secret_fields = [
            ("postgresql", "admin_user_password"),
            ("aws", "access_key_id"),
            ("aws", "secret_access_key"),
        ]

        for secret_section, secret_att in secret_fields:
            if self.__dict__[secret_section].__dict__[
                secret_att
            ] and self.__dict__[secret_section].__dict__[
                secret_att
            ].startswith(
                "$ANSIBLE_VAULT"
            ):
                secrets_found += 1
                if (
                    not self.vault_password_file
                    and not default_vault_password_file
                ):
                    logger.warning(
                        "Could not decrypt secrets - vault_password_file set"
                    )
                    return secrets_found, decrypted
                try:
                    decrypted_secret = decrypt_vault_secret(
                        self.__dict__[secret_section].__dict__[secret_att],
                        self.vault_password_file
                        or default_vault_password_file,
                    )
                    if decrypted_secret:
                        self.__dict__[secret_section].__dict__[
                            secret_att
                        ] = decrypted_secret
                        decrypted += 1
                except Exception:
                    logger.exception(
                        "Failed to decrypt %s.%s", secret_section, secret_att
                    )
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

    @model_validator(mode="after")
    def check_backup_encryption_key_set(self) -> Self:
        if (
            self.backup.type == BACKUP_TYPE_PGBACKREST
            and self.backup.encryption
        ):
            if not (
                self.backup.cipher_password or self.backup.cipher_password_file
            ):
                raise ValueError(
                    "Backup encryption assumes cipher_password / cipher_password_file set"
                )
        return self

    @model_validator(mode="after")
    def check_valid_instance_name(self) -> Self:
        if not re.match(r"^[a-z0-9\-]+$", self.instance_name):
            raise ValueError(r"Invalid instance_name. Expected: ^[a-z0-9\-]+$")
        return self

    @model_validator(mode="after")
    def check_valid_storage_type(self) -> Self:
        if self.vm.storage_type not in ("local", "network"):
            raise ValueError(
                "Invalid vm.storage_type. Expected: local | network"
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
