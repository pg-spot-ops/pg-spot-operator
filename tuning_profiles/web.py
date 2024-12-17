#!/usr/bin/env python3

import json
import sys


PROFILE = "web"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: $profile.py json_str_input")
        exit(1)

    i = json.loads(sys.argv[1])
    o = {}

    if i["postgres_version"] < 14:
        raise Exception("v14 and below not supported yet")

    ram_mb = (i.get("ram_min") or 1) * 1024
    cpus = i.get("cpu_min") or 2
    storage_type = i.get("storage_type") or "network"  # local | network
    storage_speed_class = i.get("storage_speed_class") or "ssd"  # any | hdd | ssd | nvme
    random_page_cost_map = {"local": {"hdd": 2.5, "ssd": 1.25, "nvme": 1.0}, "network": {"hdd": 4, "ssd": 1.5, "nvme": 1.1}}

    shared_buffers_mb = max(int(ram_mb * 0.15), 128)
    o["shared_buffers"] = str(shared_buffers_mb) + "MB"
    o["effective_cache_size"] = str(ram_mb - shared_buffers_mb) + "MB"
    o["maintenance_work_mem"] = str(int(ram_mb * 0.05)) + "MB"
    o["max_connections"] = max(100, min(cpus * 50, 1000))
    work_mem = int((ram_mb - shared_buffers_mb) / o["max_connections"] / 4)  # 2 is default parallelism
    if work_mem > 4:
        o["work_mem"] = str(work_mem) + "MB"
    if random_page_cost_map.get(storage_type, {}).get(storage_speed_class):
        o["random_page_cost"] = random_page_cost_map[storage_type][storage_speed_class]
    if storage_type in ["ssd", "nvme"]:
        o["effective_io_concurrency"] = 200
        o["maintenance_io_concurrency"] = 100
    o["checkpoint_completion_target"] = 0.9
    if storage_speed_class in ["ssd", "nvme"]:
        o["max_wal_size"] = "4GB" if storage_speed_class == "ssd" else "8GB"
    if cpus > 8:
        o["max_worker_processes"] = cpus
        o["max_parallel_workers"] = int(min(cpus / 4, 4))
        o["max_parallel_maintenance_workers"] = int(min(cpus / 4, 4))
    o["jit"] = "off"

    print(f"# Applied tuning profile: {PROFILE}")
    for k, v in sorted(o.items()):
        print(f"{k} = {v}")
