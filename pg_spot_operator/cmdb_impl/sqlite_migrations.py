DDL_MIGRATIONS: list[str] = []

# Roll-forward only approach!
# Sqlite driver handles only 1 stmt at a time
DDL_MIGRATIONS.append(
    """
/*
drop table if exists schema_evolution_log ;
drop table if exists instance ;
drop table if exists vm ;
drop table if exists manifest_snapshot;
*/

-- PS all timestamps are UTC!

CREATE TABLE instance (
  "uuid" text PRIMARY KEY NOT NULL,
  cloud text NOT NULL,
  region text NOT NULL,
  instance_name text NOT NULL,
  postgres_version int NOT NULL,
  cpu_min int,
  ram_min int,
  storage_min int,
  storage_type text,
  storage_speed_class text,
  tuning_profile text,
  user_tags json NOT NULL DEFAULT '{}',
  admin_user text,
  admin_is_real_superuser boolean NOT NULL DEFAULT true,
  created_on datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_modified_on datetime,
  deleted_on datetime,
  UNIQUE (cloud, "instance_name")
);
"""
)

DDL_MIGRATIONS.append(
    """
CREATE UNIQUE INDEX instance_instance_name_uq ON instance (instance_name) WHERE deleted_on IS NULL;
"""
)

DDL_MIGRATIONS.append(
    """
CREATE TABLE vm (
  id INTEGER PRIMARY KEY,
  instance_uuid text NOT NULL REFERENCES instance("uuid"),
  provider_id text NOT NULL UNIQUE,
  provider_name text,
  cloud text NOT NULL,
  region text NOT NULL,
  availability_zone text,
  sku text NOT NULL,
  price_spot DECIMAL, -- monthly
  price_ondemand DECIMAL,
  cpu int,
  ram int,
  instance_storage int,  -- local / volatile disks
  volume_id text,
  login_user text NOT NULL,
  ip_public text,
  ip_private text NOT NULL,
  user_tags json NOT NULL DEFAULT '{}',
  created_on datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_modified_on timestamp,
  deleted_on timestamp
);
"""
)

DDL_MIGRATIONS.append(
    """CREATE INDEX vm_instance_uuid ON vm (instance_uuid);"""
)

DDL_MIGRATIONS.append(
    """
CREATE TABLE manifest_snapshot (
  id INTEGER PRIMARY KEY,
  instance_uuid text NOT NULL REFERENCES instance("uuid"),
  created_on datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  setup_finished_on datetime,
  manifest text NOT NULL
);
"""
)

DDL_MIGRATIONS.append(
    """CREATE INDEX manifest_snapshot_instance_uuid ON manifest_snapshot (instance_uuid);"""
)

DDL_MIGRATIONS.append(
    """
CREATE TABLE ignored_instance (
  instance_name text NOT NULL,
  created_on datetime NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
)
