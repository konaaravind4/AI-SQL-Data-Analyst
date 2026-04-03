"""
backend/database.py — Async PostgreSQL connection and schema introspection.
"""

import os
import logging
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text, inspect

logger = logging.getLogger(__name__)


def _get_sync_engine():
    url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/analyst")
    return create_engine(url)


def get_schema(engine=None) -> str:
    """
    Introspect the connected PostgreSQL database and return a text DDL summary.

    Returns:
        Multiline string describing tables and columns.
    """
    if engine is None:
        engine = _get_sync_engine()

    inspector = inspect(engine)
    lines = []
    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        col_defs = ", ".join(f"{c['name']} {c['type']}" for c in columns)
        lines.append(f"TABLE {table_name} ({col_defs})")
    return "\n".join(lines)


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
