# Extensions

By default, only the ubiquitous `pg_stat_statements` extensions is enabled, any other extensions available from the official
PGDG repos require some configuration.

PS The extensions relevant parameters work together, i.e. just adding *timescaledb* to `--extensions` is not enough -
if the extension uses background workers or shared memory, it also needs to be added to `--shared-preload-libraries` and
for non-contrib packages (except *timescaledb*) one also needs to ensure that the OS package is installed via `--os-extra-packages`. 

## Relevant parameters

* --postgres-version / POSTGRES_VERSION - Recommended if explicitly enabling extensions
* --extensions / EXTENSIONS - List of extensions to pre-create during setup via *CREATE EXTENSION*. Not really necessary
  when using a real superuser admin user that has the according powers. 
* --shared-preload-libraries / SHARED_PRELOAD_LIBRARIES - List of extensions to pre-load on Postgres startup
* --os-extra-packages / OS_EXTRA_PACKAGES - List of packages to be installed via `apt`. It's currently the users job
  to ensure that OS packages for non-contrib extensions are installed.

## TimescaleDB example 

```bash
docker run ... \
  -e EXTENSIONS=timescaledb,pg_stat_statements \
  -e SHARED_PRELOAD_LIBRARIES=timescaledb,pg_stat_statements \
  ...
  pgspotops/pg-spot-operator:latest
```

PS For Timescaledb (as it's a common extension), the repository and package (timescaledb-2-postgresql-$postgres.version)
are added behind the scenes.
