import logging
from dataclasses import dataclass
from typing import Any

from pg_spot_operator.util import pg_size_bytes

logger = logging.getLogger(__name__)


@dataclass
class TuningInput:
    postgres_version: int
    ram_mb: int
    cpus: int
    storage_type: str  # network | local
    storage_speed_class: str  # any | hdd | ssd | nvme


TUNING_PROFILE_DEFAULT = (
    "default"  # A conservative update to Postgres defaults, 20% shared_buffers
)
TUNING_PROFILE_OLTP = "oltp"  # Write-heavy accent, larger 30% shared_buffers, higher JIT threshold
TUNING_PROFILE_WEB = (
    "web"  # More sessions / max_connections, smaller 15% buffers to avoid OOM
)
TUNING_PROFILE_ANALYTICS = "analytics"  # Batching accent, delayed checkpointing, low session count, 25% SB
TUNING_PROFILE_THROWAWAY = "throwaway"  # Testing, data loading etc, fsync off, full_page_writes, large work_mem

TUNING_PROFILES = [
    "none",
    TUNING_PROFILE_DEFAULT,
    TUNING_PROFILE_OLTP,
    TUNING_PROFILE_WEB,
    TUNING_PROFILE_ANALYTICS,
    TUNING_PROFILE_THROWAWAY,
]
RANDOM_PAGE_COST_MAP = {
    "local": {"hdd": 2.5, "ssd": 1.25, "nvme": 1.0},
    "network": {"hdd": 4, "ssd": 1.5, "nvme": 1.25},
}


def apply_base_tuning(ti: TuningInput) -> dict[str, Any]:
    o: dict[str, Any] = {}

    shared_buffers_mb = int(max(int(ti.ram_mb * 0.20), 128))
    o["shared_buffers"] = str(shared_buffers_mb) + "MB"
    o["effective_cache_size"] = str(ti.ram_mb - shared_buffers_mb) + "MB"
    o["maintenance_work_mem"] = str(int(ti.ram_mb * 0.05)) + "MB"
    o["max_connections"] = max(100, min(ti.cpus * 50, 500))
    work_mem = int(
        (ti.ram_mb - shared_buffers_mb) / o["max_connections"] / 2
    )  # 2 is default parallelism
    if work_mem > 4:
        o["work_mem"] = str(work_mem) + "MB"
    if RANDOM_PAGE_COST_MAP.get(ti.storage_type, {}).get(
        ti.storage_speed_class
    ):
        o["random_page_cost"] = RANDOM_PAGE_COST_MAP[ti.storage_type][
            ti.storage_speed_class
        ]
    if ti.storage_type in ["ssd", "nvme"]:
        o["effective_io_concurrency"] = 200
        o["maintenance_io_concurrency"] = 100
    o["checkpoint_completion_target"] = 0.9
    o["checkpoint_timeout"] = "15min"
    if ti.storage_speed_class in ["ssd", "nvme"]:
        o["max_wal_size"] = "4GB" if ti.storage_speed_class == "ssd" else "8GB"
    if ti.cpus > 8:
        o["max_worker_processes"] = ti.cpus
        o["max_parallel_workers"] = ti.cpus
        o["max_parallel_workers_per_gather"] = int(min(ti.cpus / 4, 4)) or 2
        o["max_parallel_maintenance_workers"] = int(min(ti.cpus / 4, 4)) or 2

    return o


def apply_oltp(ti: TuningInput, base: dict[str, Any]) -> dict[str, Any]:
    shared_buffers_mb = int(max(int(ti.ram_mb * 0.30), 128))
    base["shared_buffers"] = str(shared_buffers_mb) + "MB"
    base["checkpoint_timeout"] = "10min"
    base["backend_flush_after"] = "2MB"
    base["jit_above_cost"] = 1000000  # 10x from default
    return base


def apply_web(ti: TuningInput, base: dict[str, Any]) -> dict[str, Any]:
    shared_buffers_mb = int(max(int(ti.ram_mb * 0.15), 128))
    base["max_connections"] = max(100, min(ti.cpus * 50, 1000))
    base["shared_buffers"] = str(shared_buffers_mb) + "MB"
    base["jit_above_cost"] = 1000000  # 10x from default
    return base


def apply_analytics(ti: TuningInput, base: dict[str, Any]) -> dict[str, Any]:
    shared_buffers_mb = int(max(int(ti.ram_mb * 0.25), 128))
    base["shared_buffers"] = str(shared_buffers_mb) + "MB"
    work_mem = max(
        64,
        int(
            (ti.ram_mb - shared_buffers_mb)
            / base.get("max_connections", 100)
            / 2
        ),
    )
    if work_mem > 4:
        base["work_mem"] = str(work_mem) + "MB"
    base["checkpoint_timeout"] = "30min"
    base["max_wal_size"] = (
        "16GB" if ti.storage_speed_class in ["ssd", "nvme"] else "16GB"
    )
    return base


def apply_throwaway(ti: TuningInput, base: dict[str, Any]) -> dict[str, Any]:
    base = apply_analytics(ti, base)
    base["fsync"] = "off"
    base["full_page_writes"] = "off"
    return base


def activate_huge_pages(base_tuned: dict[str, Any]) -> dict[str, Any]:
    """Setting a 3% extra margin seems to work. Background - Postgres also wants to pre-allocate some structures for
    connection slots and locks. If set too high the memory for huge pages remains reserved and unavailable for general use.
    """
    base_tuned["huge_pages"] = (
        "try"  # Stay on default 'try' for a test period still instead of 'on' which fails if not enough huge pages available
    )
    base_tuned["huge_page_size"] = "2MB"
    sb_bytes = pg_size_bytes(base_tuned["shared_buffers"])
    base_tuned["pg_spot_operator_shadow_os_huge_pages_needed"] = int(
        (sb_bytes / (2048 * 1024)) * 1.03
    )
    return base_tuned


def apply_postgres_tuning(
    ti: TuningInput, tuning_profile: str
) -> dict[str, Any]:
    """Common starting point for all other profiles"""

    if ti.postgres_version < 14:
        raise Exception("Postgres v14 and below not supported")

    logger.debug("Tuning Postgres based on following HW info: %s", ti)
    base_tuned = apply_base_tuning(ti)

    if tuning_profile.lower() == TUNING_PROFILE_OLTP:
        base_tuned = apply_oltp(ti, base_tuned)
    elif tuning_profile.lower() == TUNING_PROFILE_WEB:
        base_tuned = apply_web(ti, base_tuned)
    elif tuning_profile.lower() == TUNING_PROFILE_ANALYTICS:
        base_tuned = apply_analytics(ti, base_tuned)
    elif tuning_profile.lower() == TUNING_PROFILE_THROWAWAY:
        base_tuned = apply_throwaway(ti, base_tuned)

    if pg_size_bytes(base_tuned["shared_buffers"]) > pg_size_bytes(
        "8GB"
    ):  # Require huge pages from 8GB SB
        base_tuned = activate_huge_pages(base_tuned)

    return base_tuned
