import copy
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
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
from sqlalchemy.engine.base import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from pg_spot_operator import manifests, util
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
    major_ver: Mapped[Optional[int]] = mapped_column(Integer, nullable=False)
    cpu_min: Mapped[Optional[int]]
    ram_min: Mapped[Optional[int]]
    storage_min: Mapped[Optional[int]]
    storage_type: Mapped[Optional[str]]
    storage_speed_class: Mapped[Optional[str]]
    tuning_profile: Mapped[Optional[str]]
    user_tags: Mapped[dict] = mapped_column(JSON, nullable=False)
    admin_user: Mapped[Optional[str]]
    admin_is_real_superuser: Mapped[Optional[bool]]
    admin_password: Mapped[Optional[str]]
    connstr_private: Mapped[Optional[str]]
    connstr_public: Mapped[Optional[str]]
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
    aws_profile: str | None = None
    gcp_project_id: str | None = None
    azure_subscription_id: str | None = None
    azure_resource_group: str | None = None

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
    aws_profile: Mapped[Optional[str]]
    gcp_project_id: Mapped[Optional[str]]
    azure_subscription_id: Mapped[Optional[str]]
    azure_resource_group: Mapped[Optional[str]]

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


def init_engine_and_check_connection(sqlite_connstr: str):
    sqlite_path = os.path.expanduser(sqlite_connstr)
    logger.info("Initializing CMDB sqlite3 engine at %s ...", sqlite_path)
    if not os.path.exists(os.path.dirname(sqlite_path)):
        os.mkdir(os.path.dirname(sqlite_path))
    global engine
    engine = sqlalchemy.create_engine(
        f"sqlite+pysqlite:///{sqlite_path}", echo=False
    )
    c = engine.connect()
    sqlite.set_connstr(sqlite_path)
    c.close()
    logger.info("OK - engine initialized")


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

        logger.info(
            "Storing new instance %s (%s) to CMDB ...",
            m.instance_name,
            m.cloud,
        )
        i = Instance()
        i.uuid = m.uuid
        i.cloud = m.cloud
        i.region = m.region
        i.instance_name = m.instance_name
        i.major_ver = m.pg.major_ver
        i.cpu_min = m.vm.cpu_min
        i.storage_min = m.vm.storage_min
        i.storage_type = m.vm.storage_type
        i.storage_speed_class = m.vm.storage_speed_class
        i.tuning_profile = m.pg_config.tuning_profile
        i.user_tags = m.user_tags
        i.admin_user = m.pg.admin_user
        i.admin_password = m.pg.admin_user_password
        i.admin_is_real_superuser = m.pg.admin_is_real_superuser

        session.add(i)
        session.commit()
        logger.info(
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
        logger.info("OK - inserted snapshot with ID %s", snap.id)
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
    return


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


def update_instance_connect_info(m: InstanceManifest) -> tuple[str, str]:
    """Returns [connstr_private, connstr_public]"""
    logger.debug(
        "Updating instance %s UUID %s connect info in CMDB",
        m.instance_name,
        m.uuid,
    )
    vm = get_latest_vm_by_uuid(m.uuid)
    if not vm:
        raise Exception(
            f"No active VMs found for instance {m.instance_name} ({m.cloud}) to set connect string"
        )

    with Session(engine) as session:
        stmt = select(Instance).where(Instance.uuid == m.uuid)
        instance = session.scalars(stmt).first()
        if not instance:
            raise Exception(
                f"Expected instance with UUID {m.uuid} to be registered in CMDB"
            )
        if m.pg.admin_user and m.pg.admin_user_password:
            instance.connstr_private = util.compose_postgres_connstr_uri(
                vm.ip_private,
                m.pg.admin_user,
                m.pg.admin_user_password,
                dbname=m.pg.ensure_app_dbname or "postgres",
            )
            if vm.ip_public:
                instance.connstr_public = util.compose_postgres_connstr_uri(
                    vm.ip_public,
                    m.pg.admin_user,
                    m.pg.admin_user_password,
                    dbname=m.pg.ensure_app_dbname or "postgres",
                )
        else:
            instance.connstr_private = util.get_local_postgres_connstr()
            instance.connstr_public = ""
        session.commit()
        logger.debug(
            "Updated instance %s connect string(s) in CMDB", m.instance_name
        )
        return instance.connstr_private, instance.connstr_public or ""


def finalize_instance_setup(m: InstanceManifest):
    logger.info("Instance %s setup completed", m.instance_name)

    m.decrypt_secrets_if_any()

    connstr_private, connstr_public = update_instance_connect_info(m)
    if connstr_private:
        logger.info("*** Private connect string *** - '%s'", connstr_private)
    if connstr_public:
        logger.info("*** Public connect string *** - '%s'", connstr_public)


def finalize_ensure_vm(m: InstanceManifest, o_p: dict):
    if "provider_id" not in o_p:
        raise Exception(
            "provider_id expected as ensure_vm output"
        )  # TODO generalize for other non-nulls also

    with Session(engine) as session:
        stmt = (
            select(Vm)
            .where(Vm.cloud == m.cloud)
            .where(Vm.instance_uuid == m.uuid)
            .where(Vm.provider_id == o_p["provider_id"])
            .limit(1)
        )
        vm = session.scalars(stmt).first()
        if vm:
            logger.debug("Updating VM %s ... ", o_p["provider_id"])
        else:
            logger.debug(
                "Registering a new VM %s for %s",
                o_p["provider_id"],
                m.instance_name,
            )
            vm = Vm()
            vm.provider_id = o_p["provider_id"]

        # Mandatory
        vm.instance_uuid = m.uuid
        vm.cloud = m.cloud
        vm.region = m.region
        vm.ip_private = o_p["ip_private"]
        vm.sku = o_p["sku"]
        vm.login_user = o_p["login_user"]
        # Optional
        vm.provider_name = o_p.get("provider_name")
        vm.availability_zone = o_p.get("availability_zone")
        vm.cpu = o_p.get("cpu")
        vm.ram = o_p.get("ram")
        vm.instance_storage = o_p.get("instance_storage")
        vm.ip_public = o_p.get("ip_public")
        vm.user_tags = m.user_tags
        vm.volume_id = o_p.get("volume_id")  # If using block storage
        vm.price_spot = o_p.get("price_spot")
        vm.price_ondemand = o_p.get("price_ondemand")
        vm.last_modified_on = datetime.utcnow()

        session.add(vm)

        session.commit()
        logger.info(
            "OK - %s VM with name %s (ip_public = %s , ip_private = %s) registered for instance %s. Provider ID: %s",
            m.cloud,
            o_p.get("provider_name", "noname"),
            vm.ip_public,
            vm.ip_private,
            m.instance_name,
            o_p["provider_id"],
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

        logger.info(
            "Manifest snapshot ID %s for %s marked as completed",
            m.manifest_snapshot_id,
            m.instance_name,
        )
        session.commit()
