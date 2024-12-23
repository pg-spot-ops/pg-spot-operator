import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TuningInput:
    postgres_version: int
    ram_mb: int
    cpus: int
    storage_type: str  # network | local
    storage_speed_class: str  # any | hdd | ssd | nvme


RANDOM_PAGE_COST_MAP = {
    "local": {"hdd": 2.5, "ssd": 1.25, "nvme": 1.0},
    "network": {"hdd": 4, "ssd": 1.5, "nvme": 1.1},
}


def apply_postgres_base_tuning(ti: TuningInput) -> dict[str, Any]:
    """Common starting point for all other profiles"""

    if ti.postgres_version < 14:
        raise Exception("Postgres v14 and below not supported")

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
    if ti.storage_speed_class in ["ssd", "nvme"]:
        o["max_wal_size"] = "4GB" if ti.storage_speed_class == "ssd" else "8GB"
    if ti.cpus > 8:
        o["max_worker_processes"] = ti.cpus
        o["max_parallel_workers"] = int(min(ti.cpus / 4, 4))
        o["max_parallel_maintenance_workers"] = int(min(ti.cpus / 4, 4))
    o["jit_above_cost"] = 1000000  # 10x from default

    return o
