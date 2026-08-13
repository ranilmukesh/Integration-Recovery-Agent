import logging
import os
import sqlite3

import psycopg
from psycopg.rows import dict_row

from app.config import settings

logger = logging.getLogger("app.db")
_sqlite_keepalive = None
_db_pool = None


class PooledConnectionWrapper:
    """Wrapper that returns connection to psycopg_pool on close()."""
    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        if self._pool and self._conn:
            self._pool.putconn(self._conn)
            self._conn = None
            self._pool = None

    def __getattr__(self, name):
        return getattr(self._conn, name)


def is_postgres(db_url: str | None = None) -> bool:
    url = db_url or settings.NEON_DB_URL
    return bool(url and url.startswith(("postgresql", "postgres")))


def get_db_pool(db_url: str | None = None):
    global _db_pool
    url = db_url or settings.NEON_DB_URL
    if is_postgres(url) and _db_pool is None:
        clean_url = url.replace("postgresql+psycopg://", "postgresql://")
        try:
            import psycopg_pool
            _db_pool = psycopg_pool.ConnectionPool(
                clean_url,
                min_size=1,
                max_size=10,
                max_idle=30,       # Drop connections if idle for 30 seconds
                max_lifetime=300,  # Force recycle every 5 minutes maximum
                kwargs={
                    "row_factory": dict_row,
                    "keepalives": 1,
                    "keepalives_idle": 30,
                    "keepalives_interval": 10,
                    "keepalives_count": 5
                }
            )
            logger.info("Database connection pool initialized for Neon DB (min=1, max=10, max_idle=30s).")
        except Exception as e:
            logger.error("Failed to initialize connection pool: %s", e)
            _db_pool = None
    return _db_pool


def get_db_connection(db_url: str | None = None):
    global _sqlite_keepalive
    url = db_url or settings.NEON_DB_URL
    if is_postgres(url):
        clean_url = url.replace("postgresql+psycopg://", "postgresql://")
        pool = get_db_pool(url)
        if pool:
            try:
                conn = pool.getconn()
                return PooledConnectionWrapper(pool, conn)
            except Exception as e:
                logger.warning("[POOL FALLBACK] Failed to borrow connection from pool (%s). Direct connect fallback.", e)
        try:
            return psycopg.connect(clean_url, row_factory=dict_row)
        except Exception as e:
            if not settings.ALLOW_SQLITE_FALLBACK:
                logger.error("[CRITICAL DB FAILURE] Neon PostgreSQL connection failed: %s", e)
                raise RuntimeError(f"Database connection to Neon failed and ALLOW_SQLITE_FALLBACK is False: {e}") from e
            logger.warning("[EXPLICIT FALLBACK] Neon connection failed (%s). Using SQLite in-memory fallback (ALLOW_SQLITE_FALLBACK=True).", e)
            url = ":memory:"

    # SQLite fallback
    conn_str = "file:memdb1?mode=memory&cache=shared" if url == ":memory:" else url
    if url == ":memory:" and _sqlite_keepalive is None:
        _sqlite_keepalive = sqlite3.connect(conn_str, uri=True)
    conn = sqlite3.connect(conn_str, uri=bool(url == ":memory:" or "file:" in conn_str))
    conn.row_factory = sqlite3.Row
    return conn


def run_migrations(db_url: str | None = None):
    url = db_url or settings.NEON_DB_URL
    migration_file = os.path.join(os.path.dirname(__file__), "..", "migrations", "001_initial.sql")
    
    if not os.path.exists(migration_file):
        return

    with open(migration_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    try:
        conn = get_db_connection(url)
        try:
            cur = conn.cursor()
            try:
                if is_postgres(url):
                    cur.execute(sql_content)
                else:
                    sqlite_sql = sql_content.replace("gen_random_uuid()", "(lower(hex(randomblob(16))))")
                    sqlite_sql = sqlite_sql.replace("JSONB", "TEXT").replace("TIMESTAMPTZ", "TEXT").replace("now()", "CURRENT_TIMESTAMP")
                    sqlite_sql = sqlite_sql.replace("CREATE EXTENSION IF NOT EXISTS pgcrypto;", "")
                    sqlite_sql = sqlite_sql.replace("::jsonb", "")
                    sqlite_sql = sqlite_sql.replace("NUMERIC(4,3)", "REAL")
                    cur.executescript(sqlite_sql)
            finally:
                cur.close()
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("[Warning] DB Migration error: %s", e)

