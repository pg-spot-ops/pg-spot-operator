import logging
import sqlite3

from pg_spot_operator.cmdb_impl.sqlite import (
    sl_exec_sql_single,
    sl_exec_sql_with_cursor,
)
from pg_spot_operator.cmdb_impl.sqlite_migrations import DDL_MIGRATIONS

logger = logging.getLogger(__name__)

SQL_SCHEMA_ROLLOUT_LOG_PG = """
CREATE TABLE IF NOT EXISTS schema_evolution_log (
    evolution_id int NOT NULL PRIMARY KEY,
    created_on timestamptz NOT NULL DEFAULT now()
);
"""
SQL_SCHEMA_ROLLOUT_LOG_SL = """
CREATE TABLE IF NOT EXISTS schema_evolution_log (
    evolution_id int NOT NULL PRIMARY KEY,
    created_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

SQL_SCHEMA_ROLLOUT_MAX_ID = """SELECT coalesce(max(evolution_id), -1) AS max_id FROM schema_evolution_log;"""
SQL_SCHEMA_MARK_ROLLED_OUT_PG = (
    "INSERT INTO schema_evolution_log (evolution_id) VALUES (%s);"
)
SQL_SCHEMA_MARK_ROLLED_OUT_SL = (
    "INSERT INTO schema_evolution_log (evolution_id) VALUES (?);"
)


def do_ddl_rollout_if_needed(sqlite_connstr: str) -> int:
    """Roll-forward only approach - schema fixes are normal evolutions."""
    sl_exec_sql_single(SQL_SCHEMA_ROLLOUT_LOG_SL, None)

    rs, _ = sl_exec_sql_single(SQL_SCHEMA_ROLLOUT_MAX_ID)
    max_rolled_out_id = rs[0]["max_id"]
    if max_rolled_out_id + 1 == len(DDL_MIGRATIONS):
        logging.debug("CMDB schema already up to date")
        return 0

    migrations_applied = 0
    with sqlite3.connect(sqlite_connstr) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        for ev_id in range(max_rolled_out_id + 1, len(DDL_MIGRATIONS)):
            logging.debug("Rolling out migration ID %s ...", ev_id)
            sl_exec_sql_with_cursor(cur, DDL_MIGRATIONS[ev_id])
            sl_exec_sql_with_cursor(
                cur, SQL_SCHEMA_MARK_ROLLED_OUT_SL, (ev_id,)
            )
            migrations_applied += 1

        logging.info("CMDB schema updated to latest")
        conn.commit()
    return migrations_applied
