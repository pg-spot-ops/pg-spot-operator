# Tuning profiles

Postgres tuning profiles are simple standalone scripts that take some hardware / postgres version input and spit out
valid postgresql.conf lines related to performance and hardware, NOT extensions and such, which is handled by the engine.

The idea here is to be decoupled from the main engine and have something that is super easy for users to modify,
but at the same time with full powers (Python), to possibly reach out to some metrics DBs etc to make decisions.

PS Note that user provided Postgres config values from the manifests (pg_config.extra_config_lines) override the
generated ones in case of a conflict.

## Current builtin tuning profiles

- *default* - A conservative update to Postgres defaults, 20% shared_buffers 
- *oltp* - Write-heavy accent, larger 30% shared_buffers
- *analytics* - Batching accent, delayed checkpointing, low session count
- *web* - Lots of sessions / max_connections, smaller 15% buffers to avoid OOM


# Available inputs

The engine will pass the manifest's VM section + postgres_version + cloud + user_tags as a JSON string: 

```
cloud: aws
postgres_version: 16
vm:
    cpu_min: 2
    ram_min: 4
    storage_min: 100
    storage_type: network
    storage_speed_class: ssd
```

And gets back "ready to use" postgresql.conf lines:

```
./tuning_profiles/default.py '{"vm":{"cpu_min":4,"ram_min":16,"storage_min":100,"storage_type":"network","storage_speed_class":"ssd"},"postgres_version":16,"cloud": "aws"}'

checkpoint_completion_target = 0.9
effective_cache_size = 820MB
jit_above_cost = 1000000
maintenance_work_mem = 51MB
max_connections = 100
max_wal_size = 4GB
random_page_cost = 1.5
shared_buffers = 204MB
```


# Tuning ideas

A selection of these Postgres config generators could be of help:

* https://pgtune.leopard.in.ua/
* https://pgconfigurator.cybertec.at/
* https://www.pgconfig.org/
