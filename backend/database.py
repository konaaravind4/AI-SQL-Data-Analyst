"""
backend/database.py — PostgreSQL connection and schema introspection.

Enhanced with:
  - get_table_count()         : returns number of tables in the database
  - get_row_count(table)      : returns approximate row count for a table
  - get_column_names(table)   : returns list of column names for a table
  - KonaDB support            : if DATABASE_URL starts with 'kona://', uses kona.connect()
"""

import os
import logging
from typing import Any, List

import pandas as pd
from sqlalchemy import create_engine, text, inspect

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------

def _get_sync_engine():
    """
    Create and return a SQLAlchemy engine.

    If DATABASE_URL starts with 'kona://', a KonaDB-backed engine is used.
    Otherwise falls back to a standard PostgreSQL engine.

    Returns:
        SQLAlchemy Engine instance.
    """
    url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/analyst")

    if url.startswith("kona://"):
        return _get_kona_engine(url)

    logger.debug("Creating SQLAlchemy engine for URL scheme: %s", url.split("://")[0])
    return create_engine(url)


def _get_kona_engine(kona_url: str):
    """
    Build a SQLAlchemy-compatible engine backed by KonaDB.

    KonaDB is accessed via the `kona` package.  The URL format is:
        kona://<host>/<database>
    or simply the path to a local KonaDB file when KONA_DB_PATH is set.

    Args:
        kona_url: The 'kona://…' connection URL.

    Returns:
        SQLAlchemy Engine wrapping KonaDB.

    Raises:
        ImportError: If the `kona` package is not installed.
        RuntimeError: If the KonaDB connection cannot be established.
    """
    try:
        import kona  # type: ignore  # optional dependency
    except ImportError as exc:
        raise ImportError(
            "KonaDB support requires the 'kona' package. "
            "Install it with: pip install kona"
        ) from exc

    kona_db_path = os.getenv("KONA_DB_PATH", "")
    logger.info("Connecting to KonaDB at path: %s (url: %s)", kona_db_path, kona_url)

    try:
        # kona.connect() returns a DBAPI-2 compatible connection; wrap it
        # with SQLAlchemy using the sqlite dialect (KonaDB is SQLite-compatible)
        conn = kona.connect(kona_db_path or kona_url.replace("kona://", ""))
        # Use SQLAlchemy's creator pattern to wrap the existing connection
        engine = create_engine(
            "sqlite://",
            creator=lambda: conn,
        )
        logger.info("KonaDB engine created successfully.")
        return engine
    except Exception as exc:
        raise RuntimeError(f"Failed to connect to KonaDB: {exc}") from exc


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------

def get_schema(engine=None) -> str:
    """
    Introspect the connected database and return a text DDL summary.

    Args:
        engine: Optional SQLAlchemy engine (creates one from env if None).

    Returns:
        Multiline string describing tables and columns.
    """
    if engine is None:
        engine = _get_sync_engine()

    inspector = inspect(engine)
    lines: list[str] = []
    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        col_defs = ", ".join(f"{c['name']} {c['type']}" for c in columns)
        lines.append(f"TABLE {table_name} ({col_defs})")
    logger.debug("get_schema returned %d tables.", len(lines))
    return "\n".join(lines)


def get_table_count(engine=None) -> int:
    """
    Return the number of user tables in the connected database.

    Args:
        engine: Optional SQLAlchemy engine (creates one from env if None).

    Returns:
        Integer count of tables.

    Example:
        >>> get_table_count()
        5
    """
    if engine is None:
        engine = _get_sync_engine()

    inspector = inspect(engine)
    count = len(inspector.get_table_names())
    logger.debug("get_table_count → %d", count)
    return count


def get_row_count(table: str, engine=None) -> int:
    """
    Return the approximate row count for a given table.

    Uses a direct ``SELECT COUNT(*) FROM <table>`` query for accuracy.

    Args:
        table: Name of the table to count rows in.
        engine: Optional SQLAlchemy engine (creates one from env if None).

    Returns:
        Integer row count. Returns -1 if the table does not exist or
        the query fails.

    Example:
        >>> get_row_count("orders")
        15023
    """
    if engine is None:
        engine = _get_sync_engine()

    # Validate table name to prevent injection (only allow alphanumeric + underscore)
    import re
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table):
        logger.error("get_row_count: invalid table name '%s'", table)
        raise ValueError(f"Invalid table name: {table!r}")

    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
            row = result.fetchone()
            count = int(row[0]) if row else 0
        logger.debug("get_row_count('%s') → %d", table, count)
        return count
    except Exception as exc:
        logger.error("get_row_count failed for table '%s': %s", table, exc)
        return -1


def get_column_names(table: str, engine=None) -> List[str]:
    """
    Return the list of column names for a given table.

    Args:
        table: Name of the table to inspect.
        engine: Optional SQLAlchemy engine (creates one from env if None).

    Returns:
        List of column name strings (in schema order).

    Raises:
        ValueError: If the table name is invalid or the table does not exist.

    Example:
        >>> get_column_names("users")
        ['id', 'name', 'email', 'created_at']
    """
    if engine is None:
        engine = _get_sync_engine()

    import re
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table):
        raise ValueError(f"Invalid table name: {table!r}")

    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if table not in table_names:
        raise ValueError(f"Table '{table}' does not exist in the database.")

    columns = inspector.get_columns(table)
    names = [col["name"] for col in columns]
    logger.debug("get_column_names('%s') → %s", table, names)
    return names


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------

def execute_query(sql: str, engine=None) -> pd.DataFrame:
    """
    Run a SQL query and return results as a Pandas DataFrame.

    Args:
        sql: SQL query string to execute.
        engine: Optional SQLAlchemy engine (creates one from env if None).

    Returns:
        DataFrame containing query results.

    Raises:
        ValueError: If the SQL contains destructive statements.
        RuntimeError: On query execution failure.
    """
    _check_safe_sql(sql)

    if engine is None:
        engine = _get_sync_engine()

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = result.fetchall()
            columns = list(result.keys())
        logger.info("execute_query returned %d rows.", len(rows))
        return pd.DataFrame(rows, columns=columns)
    except Exception as exc:
        logger.error("Query execution failed: %s", exc)
        raise RuntimeError(f"Query failed: {exc}") from exc


def _check_safe_sql(sql: str) -> None:
    """Raise ValueError if the SQL contains write/destructive operations."""
    upper = sql.strip().upper()
    dangerous = ("DROP", "DELETE", "TRUNCATE", "INSERT", "UPDATE", "ALTER", "CREATE", "GRANT", "REVOKE")
    for keyword in dangerous:
        if upper.startswith(keyword) or f" {keyword} " in upper:
            raise ValueError(f"Dangerous SQL keyword detected: {keyword}. Only SELECT queries are allowed.")
