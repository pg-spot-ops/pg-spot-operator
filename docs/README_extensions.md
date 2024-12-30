# Extensions

By default, only the ubiquitous `pg_stat_statements` extensions is enabled, any other extensions available from the official
PGDG repos require some configuration. Note though, that the extensions relevant parameters work together, i.e. just
adding *timescaledb* to `--extensions` is not enough. 

## Relevant parameters

* --postgres-version / POSTGRES_VERSION - Recommended if explicitly enabling extensions
* --extensions / EXTENSIONS - List of extensions to pre-create during setup via *CREATE EXTENSION*. Not really necessary
  when using a real superuser admin user that has the according powers. 
* --shared-preload-libraries / SHARED_PRELOAD_LIBRARIES - List of extensions to pre-load on Postgres startup
* --os-extra-packages / OS_EXTRA_PACKAGES - List of packages to be installed via `apt`. It's currently the users job
  to ensure that packages for all pre-created / loaded extensions are installed.

## TimescaleDB example 

```bash
docker run ... \
  -e EXTENSIONS=timescaledb,pg_stat_statements \
  -e OS_EXTRA_PACKAGES=postgresql-16-timescaledb \
  -e SHARED_PRELOAD_LIBRARIES=timescaledb,pg_stat_statements \
  ...
  pgspotops/pg-spot-operator:latest
```
