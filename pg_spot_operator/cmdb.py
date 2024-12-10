import copy
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

import sqlalchemy
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.engine.base import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from pg_spot_operator import manifests, util
from pg_spot_operator.cloud_impl.cloud_structs import CloudVM
from pg_spot_operator.cmdb_impl import sqlite
from pg_spot_operator.manifests import InstanceManifest

logger = logging.getLogger(__name__)
engine: Engine | None = None


class Base(DeclarativeBase):
    pass


class Instance(Base):
    __tablename__ = "instance"
    uuid: Mapped[Optional[str]] = mapped_column(
        String, primary_key=True, nullable=False, default=str(uuid4())
    )
    cloud: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[Optional[str]] = mapped_column(String, nullable=False)
    instance_name: Mapped[str] = mapped_column(String, nullable=False)
    postgres_version: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=False
    )
    cpu_min: Mapped[Optional[int]]
    ram_min: Mapped[Optional[int]]
    storage_min: Mapped[Optional[int]]
    storage_type: Mapped[Optional[str]]
    storage_speed_class: Mapped[Optional[str]]
    tuning_profile: Mapped[Optional[str]]
    user_tags: Mapped[dict] = mapped_column(JSON, nullable=False)
    admin_user: Mapped[Optional[str]]
    admin_is_real_superuser: Mapped[Optional[bool]]
    created_on: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("DEFAULT")
    )
    last_modified_on: Mapped[Optional[datetime]]
    deleted_on: Mapped[Optional[datetime]]

    def __str__(self) -> str:
        return f"Instance(name={self.instance_name}, cloud={self.cloud}, uuid={self.uuid}, created_on={self.created_on})"


@dataclass
class VmDTO:
    id: int | None = None
    provider_id: str | None = None
    provider_name: str | None = None
    instance_uuid: str | None = None
    cloud: str | None = None
    region: str | None = None
    availability_zone: str | None = None
    sku: str | None = None
    price_spot: float | None = None
    price_ondemand: float | None = None
    cpu: int | None = None
    ram: int | None = None
    instance_storage: int | None = None
    volume_id: str | None = None
    instance_type: str | None = None
    login_user: str | None = None
    ip_public: str | None = None
    ip_private: str | None = None
    user_tags: dict = field(default_factory=dict)
    created_on: datetime | None = None
    last_modified_on: datetime | None = None
    deleted_on: datetime | None = None

    def __str__(self) -> str:
        return f"VmDTO(instance_uuid={self.instance_uuid}, provider_id={self.provider_id}, cloud={self.cloud}, ip_public={self.ip_public}, ip_private={self.ip_private})"


class Vm(Base):
    __tablename__ = "vm"
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    provider_id: Mapped[str] = mapped_column(String, nullable=False)
    provider_name: Mapped[Optional[str]]
    instance_uuid: Mapped[Optional[str]] = mapped_column(
        String, nullable=False
    )
    cloud: Mapped[Optional[str]] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, nullable=False)
    availability_zone: Mapped[Optional[str]]
    sku: Mapped[str] = mapped_column(String, nullable=False)
    price_spot: Mapped[Optional[float]]
    price_ondemand: Mapped[Optional[float]]
    cpu: Mapped[Optional[int]]
    ram: Mapped[Optional[int]]
    instance_storage: Mapped[Optional[int]]
    volume_id: Mapped[Optional[str]]
    login_user: Mapped[str] = mapped_column(String, nullable=False)
    ip_public: Mapped[Optional[str]]
    ip_private: Mapped[str] = mapped_column(String, nullable=False)
    user_tags: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_on: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("DEFAULT")
    )
    last_modified_on: Mapped[Optional[datetime]]
    deleted_on: Mapped[Optional[datetime]]

    def __str__(self) -> str:
        return f"VM(instance_uuid={self.instance_uuid}, provider_id={self.provider_id}, cloud={self.cloud}, ip_public={self.ip_public}, ip_private={self.ip_private})"

    def to_dto(self) -> VmDTO:
        dc = copy.deepcopy(self.__dict__)
        dc.pop("_sa_instance_state") if "_sa_instance_state" in dc else None
        return VmDTO(**dc)


class ManifestSnapshot(Base):
    __tablename__ = "manifest_snapshot"
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    instance_uuid: Mapped[str] = mapped_column(
        String, ForeignKey("instance.uuid")
    )
    created_on: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("DEFAULT")
    )
    manifest: Mapped[Optional[str]] = mapped_column(String, nullable=False)
    setup_finished_on: Mapped[Optional[datetime]]

    def __repr__(self) -> str:
        return f"ManifestSnapshot(id={self.id}, instance_uuid={self.instance_uuid}, created_on={self.created_on})"


class IgnoredInstance(Base):
    __tablename__ = "ignored_instance"
    instance_name: Mapped[str] = mapped_column(String, primary_key=True)
    created_on: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("DEFAULT")
    )


def init_engine_and_check_connection(sqlite_connstr: str):
    sqlite_path = os.path.expanduser(sqlite_connstr)
    logger.debug("Initializing CMDB sqlite3 engine at %s ...", sqlite_path)
    if not os.path.exists(os.path.dirname(sqlite_path)):
        os.mkdir(os.path.dirname(sqlite_path))
    global engine
    engine = sqlalchemy.create_engine(
        f"sqlite+pysqlite:///{sqlite_path}", echo=False
    )
    c = engine.connect()
    sqlite.set_connstr(sqlite_path)
    c.close()
    logger.debug("OK - engine initialized")


def get_instance_by_name_if_alive(m: InstanceManifest) -> Instance | None:
    """Returns the Instance if manifest already registered"""
    with Session(engine) as session:
        # Check if exists
        stmt = (
            select(Instance)
            .where(Instance.instance_name == m.instance_name)
            .where(Instance.deleted_on.is_(None))
        )
        row = session.scalars(stmt).first()
        if row:
            return row
        return None


def get_instance_by_name_cloud(m: InstanceManifest) -> Instance | None:
    """Returns the Instance if manifest already registered"""
    with Session(engine) as session:
        # Check if exists
        stmt = (
            select(Instance)
            .where(Instance.instance_name == m.instance_name)
            .where(Instance.cloud == m.cloud)
        )
        row = session.scalars(stmt).first()
        if row:
            return row
        return None


def register_instance_or_get_uuid(
    m: InstanceManifest,
) -> str | None:
    """Returns the internal UUID on success"""
    with Session(engine) as session:
        # Check if exists
        stmt = (
            select(Instance)
            .where(Instance.instance_name == m.instance_name)
            .where(Instance.cloud == m.cloud)
            .where(Instance.deleted_on.is_(None))
        )
        row = session.scalars(stmt).first()
        if row:
            logger.debug(
                "Instance '%s' found from CMDB with UUID %s",
                m.instance_name,
                row.uuid,
            )
            return row.uuid

        logger.debug(
            "Storing new instance %s (%s) to CMDB ...",
            m.instance_name,
            m.cloud,
        )
        i = Instance()
        i.uuid = m.uuid
        i.cloud = m.cloud
        i.region = m.region
        i.instance_name = m.instance_name
        i.postgres_version = m.postgres.version
        i.cpu_min = m.vm.cpu_min
        i.storage_min = m.vm.storage_min
        i.storage_type = m.vm.storage_type
        i.storage_speed_class = m.vm.storage_speed_class
        i.tuning_profile = m.postgres.tuning_profile
        i.user_tags = m.user_tags
        i.admin_user = m.postgres.admin_user
        i.admin_is_real_superuser = m.postgres.admin_is_superuser

        session.add(i)
        session.commit()
        logger.debug(
            "OK, instance '%s' stored with UUID %s",
            m.instance_name,
            i.uuid,
        )
        return i.uuid


def store_manifest_snapshot_if_changed(m: InstanceManifest) -> int:
    with Session(engine) as session:
        stmt = (
            select(ManifestSnapshot)
            .where(ManifestSnapshot.instance_uuid == m.uuid)
            .order_by(ManifestSnapshot.created_on.desc())
            .limit(1)
        )
        row = session.scalars(stmt).first()
        if row:  # Prev manifest exists, compare
            m_prev = manifests.load_manifest_from_string(row.manifest)
            if not m_prev:  # Back-serialization needs to work
                raise Exception(
                    f"Failed to load manifest from InstanceManifestSnapshot entry {row.id}"
                )
            m_prev.original_manifest = row.manifest  # type: ignore

            diff = m.diff_manifests(m_prev, original_manifests_only=True)
            if diff:
                logger.debug("Manifest change detected: %s", diff)
            else:
                logger.debug(
                    "No manifest changes detected for %s with snapshot %s",
                    m.instance_name,
                    row.id,
                )
            if not diff:
                return row.id

        logger.debug(
            "Updating manifest snapshot in CMDB for manifest %s ...", m.uuid
        )
        snap = ManifestSnapshot()
        snap.manifest = m.original_manifest
        snap.instance_uuid = m.uuid  # type: ignore
        session.add(snap)
        session.commit()
        logger.debug("OK - inserted snapshot with ID %s", snap.id)
        return snap.id


def get_last_successful_manifest_if_any(
    uuid: str | None,
) -> InstanceManifest | None:
    """Returns (manifest, already_processed)"""

    if not uuid:
        raise Exception("Valid UUID expected")

    with Session(engine) as session:
        stmt = (
            select(ManifestSnapshot)
            .where(ManifestSnapshot.instance_uuid == uuid)
            .where(ManifestSnapshot.setup_finished_on.is_not(None))
            .order_by(ManifestSnapshot.created_on.desc())
            .limit(1)
        )
        row = session.scalars(stmt).first()
        if not row:
            logger.debug(
                "No previous successful manifest found for UUID %s", uuid
            )
            return None

        logging.debug(
            "Loading InstanceManifest from ManifestSnapshot entry ID %s ...",
            row.id,
        )
        m = manifests.load_manifest_from_string(row.manifest)
        if not m:
            logging.warning(
                "Failed to load InstanceManifest from ManifestSnapshot entry %s",
                row.id,
            )
            return None
        m.manifest_snapshot_id = row.id
        m.original_manifest = row.manifest  # type: ignore

        return m


def get_latest_vm_by_uuid(instance_uuid: str | None) -> Vm | None:
    with Session(engine) as session:
        stmt = (
            select(Vm)
            .where(Vm.instance_uuid == instance_uuid)
            .where(Vm.deleted_on.is_(None))
            .order_by(Vm.created_on.desc())
        )
        row = session.scalars(stmt).first()
        if row:
            return row
    return None


def get_all_launched_active_vms(
    instance_uuid: str | None = None,
    active_cloud: str = "",
) -> list[VmDTO]:
    ret = []
    with Session(engine) as session:
        if instance_uuid:
            stmt = (
                select(Vm)
                .where(Vm.deleted_on.is_(None))
                .where(Vm.instance_uuid == instance_uuid)
                .join(Instance, Vm.instance_uuid == Instance.uuid)
                .where(Instance.deleted_on.is_(None))
            )
        else:
            stmt = (
                select(Vm)
                .where(Vm.deleted_on.is_(None))
                .join(Instance, Vm.instance_uuid == Instance.uuid)
                .where(Instance.deleted_on.is_(None))
            )
            if active_cloud:
                stmt = stmt.where(Instance.cloud == active_cloud)
        rows = session.scalars(stmt).all()
        if rows:
            for r in rows:
                ret.append(r.to_dto())
    return ret


def mark_any_active_vms_as_deleted(
    m: InstanceManifest,
) -> None:
    with Session(engine) as session:
        stmt = (
            update(Vm)
            .where(Vm.cloud == m.cloud)
            .where(Vm.instance_uuid == m.uuid)
            .where(Vm.deleted_on.is_(None))
            .values(deleted_on=datetime.utcnow())
        )
        session.execute(stmt)
        session.commit()
    return


def add_instance_to_ignore_list(instance_name: str) -> None:
    with Session(engine) as session:
        insert_stmt = Insert(IgnoredInstance).values(
            instance_name=instance_name
        )
        insert_stmt.on_conflict_do_nothing(index_elements=["instance_name"])
        session.execute(insert_stmt)
        session.commit()


def is_instance_ignore_listed(instance_name: str) -> bool:
    with Session(engine) as session:
        stmt = select(IgnoredInstance).where(
            IgnoredInstance.instance_name == instance_name
        )
        row = session.scalars(stmt).first()
        if row:
            return True
        else:
            return False


def load_manifest_by_snapshot_id(
    manifest_snapshot_id: int | None,
) -> InstanceManifest | None:
    with Session(engine) as session:
        stmt = select(ManifestSnapshot).where(
            ManifestSnapshot.id == manifest_snapshot_id
        )
        row = session.scalars(stmt).first()
        if row:
            m = manifests.load_manifest_from_string(row.manifest)
            ins = get_instance_by_name_if_alive(m)
            if not ins:
                raise Exception(
                    f"Instance {m.instance_name} not found / destroyed already, can't load snapshot"
                )
            m.uuid = ins.uuid
            m.original_manifest = row.manifest  # type: ignore
            m.fill_in_defaults()
            return m
    return None


def get_instance_connect_string(m: InstanceManifest) -> str:
    """Return a public connstr if a public instance otherwise private or local connstr"""
    main_ip: str = ""
    if m.vm.host:
        main_ip = m.vm.host
    else:
        vm = get_latest_vm_by_uuid(m.uuid)
        if not vm:
            raise Exception(
                f"No active VMs found for instance {m.instance_name} ({m.cloud}) to get connect string"
            )
        main_ip = vm.ip_public if vm.ip_public else vm.ip_private

    if m.postgres.admin_user and m.postgres.admin_password:
        return util.compose_postgres_connstr_uri(
            main_ip,
            m.postgres.admin_user,
            m.postgres.admin_password,
            dbname=m.postgres.app_db_name or "postgres",
        )
    else:
        return util.get_local_postgres_connstr()


def get_instance_connect_strings(m: InstanceManifest) -> tuple[str, str]:
    """Returns [connstr_private, connstr_public]"""
    vm: Vm | None = None
    if not (m.vm.host and m.vm.login_user):
        vm = get_latest_vm_by_uuid(m.uuid)
        if not vm:
            raise Exception(
                f"No active VMs found for instance {m.instance_name} ({m.cloud}) to set connect string"
            )

    connstr_private = util.get_local_postgres_connstr()
    connstr_public = ""
    if m.postgres.admin_user and m.postgres.admin_password:
        connstr_private = util.compose_postgres_connstr_uri(
            vm.ip_private if vm else m.vm.host,
            m.postgres.admin_user,
            m.postgres.admin_password,
            dbname=m.postgres.app_db_name or "postgres",
        )
        if m.assign_public_ip and vm and vm.ip_public and m:
            connstr_public = util.compose_postgres_connstr_uri(
                vm.ip_public if vm.ip_public else m.vm.host,
                m.postgres.admin_user,
                m.postgres.admin_password,
                dbname=m.postgres.app_db_name or "postgres",
            )
    return connstr_private, connstr_public


def get_ssh_connstr(m: InstanceManifest, connstr_format: str = "ssh") -> str:
    if connstr_format == "ssh":
        if m.vm.host and m.vm.login_user:
            return f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3 -l {m.vm.login_user} {m.vm.host}"
        vm = get_latest_vm_by_uuid(m.uuid)
        if not vm:
            return ""
        if m.ansible.private_key:
            return f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3 -l {vm.login_user} -i {m.ansible.private_key} {vm.ip_public or vm.ip_private}"
        return f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3 -l {vm.login_user} {vm.ip_public or vm.ip_private}"
    elif connstr_format == "ansible":
        if m.vm.host and m.vm.login_user:
            inventory_string = f"{m.vm.host} ansible_user={m.vm.login_user}"
            if m.ansible.private_key:
                inventory_string += (
                    f" ansible_ssh_private_key_file={m.ansible.private_key}"
                )
            return inventory_string

        vm = get_latest_vm_by_uuid(m.uuid)
        if not vm:
            return ""

        inventory_string = f"{vm.ip_public or vm.ip_private} ansible_user={vm.login_user} ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'"

        if m.ansible.private_key:
            inventory_string += (
                f" ansible_ssh_private_key_file={m.ansible.private_key}"
            )

        return inventory_string
    else:
        raise Exception(f"Unexpected connstr_format: {connstr_format}")


def finalize_ensure_vm(m: InstanceManifest, vm: CloudVM):
    if not (
        vm.provider_id and vm.instance_type and vm.login_user and vm.ip_private
    ):
        raise Exception(
            "CloudVM required fields missing - provider_id, instance_type, login_user, ip_private"
        )  # TODO generalize for other non-nulls also

    with Session(engine) as session:
        stmt = (
            select(Vm)
            .where(Vm.cloud == m.cloud)
            .where(Vm.instance_uuid == m.uuid)
            .where(Vm.provider_id == vm.provider_id)
            .limit(1)
        )
        cmdb_vm = session.scalars(stmt).first()
        if cmdb_vm:
            logger.debug("Updating VM %s ... ", vm.provider_id)
        else:
            logger.debug(
                "Registering a new VM %s for %s",
                vm.provider_id,
                m.instance_name,
            )
            cmdb_vm = Vm()
            cmdb_vm.provider_id = vm.provider_id

        # Mandatory
        cmdb_vm.instance_uuid = m.uuid
        cmdb_vm.cloud = m.cloud
        cmdb_vm.region = m.region
        cmdb_vm.ip_private = vm.ip_private
        cmdb_vm.sku = vm.instance_type
        cmdb_vm.login_user = vm.login_user
        # Optional
        cmdb_vm.provider_name = vm.provider_name
        cmdb_vm.availability_zone = vm.availability_zone
        if vm.instance_type_info:
            cmdb_vm.cpu = vm.instance_type_info.cpu
            cmdb_vm.ram = vm.instance_type_info.ram_mb
            cmdb_vm.instance_storage = vm.instance_type_info.instance_storage
            cmdb_vm.price_spot = vm.instance_type_info.monthly_spot_price
            cmdb_vm.price_ondemand = (
                vm.instance_type_info.monthly_ondemand_price
            )
        cmdb_vm.ip_public = vm.ip_public
        cmdb_vm.user_tags = m.user_tags
        cmdb_vm.volume_id = vm.volume_id  # If using block storage
        cmdb_vm.last_modified_on = datetime.utcnow()

        session.add(cmdb_vm)

        session.commit()
        logger.info(
            "OK - %s VM %s registered for instance '%s' (ip_public = %s , ip_private = %s)",
            m.cloud,
            vm.provider_id,
            m.instance_name,
            vm.ip_public,
            vm.ip_private,
        )


def finalize_destroy_instance(m: InstanceManifest):
    with Session(engine) as session:
        now = datetime.utcnow()
        stmt_vm = (
            update(Vm)
            .where(Vm.instance_uuid == m.uuid)
            .where(Vm.deleted_on.is_(None))
            .values(deleted_on=now)
        )
        session.execute(stmt_vm)
        stmt_instance = (
            update(Instance)
            .where(Instance.uuid == m.uuid)
            .where(Instance.deleted_on.is_(None))
            .values(deleted_on=now)
        )
        session.execute(stmt_instance)

        logger.info(
            "Instance %s marked as deleted in CMDB after successful destroy",
            m.instance_name,
        )
        session.commit()


def finalize_destroy_region(region: str) -> None:
    with Session(engine) as session:
        now = datetime.utcnow()
        stmt_vm = (
            update(Vm)
            .where(Vm.region == region)
            .where(Vm.deleted_on.is_(None))
            .values(deleted_on=now)
        )
        session.execute(stmt_vm)
        stmt_instance = (
            update(Instance)
            .where(Instance.region == region)
            .where(Instance.deleted_on.is_(None))
            .values(deleted_on=now)
        )
        session.execute(stmt_instance)

        logger.info(
            "All instance in region %s marked as deleted in CMDB",
            region,
        )
        session.commit()


def mark_manifest_snapshot_as_succeeded(m: InstanceManifest) -> None:
    with Session(engine) as session:
        now = datetime.utcnow()
        stmt_upd_snapshot = (
            update(ManifestSnapshot)
            .where(ManifestSnapshot.id == m.manifest_snapshot_id)
            .where(ManifestSnapshot.instance_uuid == m.uuid)
            .values(setup_finished_on=now)
        )
        session.execute(stmt_upd_snapshot)

        logger.debug(
            "Manifest snapshot ID %s for %s marked as completed",
            m.manifest_snapshot_id,
            m.instance_name,
        )
        session.commit()


def get_short_lifetime_instance_types_with_zone_if_any(
    instance_uuid: str,
    lookback_window_min: int = 30,
    short_uptime_threshold_sec: int = 300,
) -> list[tuple[str, str]]:
    with Session(engine) as session:
        stmt = (
            select(Vm)
            .where(Vm.instance_uuid == instance_uuid)
            .where(
                Vm.created_on
                > (datetime.utcnow() - timedelta(minutes=lookback_window_min))
            )
            .where(
                (Vm.deleted_on - Vm.created_on)
                < timedelta(seconds=short_uptime_threshold_sec)
            )
            .distinct(Vm.sku, Vm.availability_zone)
        )
        rows = session.scalars(stmt)
        if rows:
            ret = [(r.sku, str(r.availability_zone)) for r in rows]
            if ret:
                logger.debug(
                    "Discovered short lifetime (<%ss within last %smin) instance types: %s",
                    short_uptime_threshold_sec,
                    lookback_window_min,
                    ret,
                )
            return ret
    return []
