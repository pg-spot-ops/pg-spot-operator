import logging
import sqlite3

logger = logging.getLogger(__name__)
connstr = ""


def set_connstr(cs: str):
    global connstr
    connstr = cs


def exec_sql_single(
    sql: str, params: tuple | None = None, quiet: bool = False
) -> tuple[list[dict], Exception | None]:
    result = []
    # logger.debug("Executing SQL %s ...", sql)
    try:
        with sqlite3.connect(connstr) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            if params:
                res = cur.execute(sql, params)
            else:
                res = cur.execute(sql)

            result = cur.fetchall()
            if not result and res.rowcount:
                result = [{"rows_affected": str(res.rowcount)}]
            conn.commit()
    except Exception as e:
        if quiet:
            logger.exception("Failed to exec SQL %s", sql)
            return result, e
        raise
    return result, None


def exec_sql_with_cursor(
    cur: sqlite3.Cursor,
    sql: str,
    params: tuple | None = None,
    quiet: bool = False,
) -> tuple[list[dict], Exception | None]:
    result = []
    # logger.debug("Executing SQL %s ...", sql)
    try:

        if params:
            res = cur.execute(sql, params)
        else:
            res = cur.execute(sql)

        result = cur.fetchall()
        if not result and res.rowcount:
            result = [{"rows_affected": str(res.rowcount)}]
    except Exception as e:
        if quiet:
            logger.exception("Failed to exec SQL %s", sql)
            return result, e
        raise
    return result, None
