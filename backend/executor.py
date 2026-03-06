"""
Safe SQL executor with connection pooling and injection prevention.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

from backend.nl2sql import NL2SQL

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/analytics")
MAX_ROWS = int(os.getenv("MAX_RESULT_ROWS", "10000"))


class QueryExecutor:
    """
    Executes validated SQL queries against PostgreSQL with connection pooling.
    Returns pandas DataFrames for downstream chart rendering.
    """

    def __init__(self, database_url: str = DATABASE_URL):
        self.engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
        )

    def execute(self, sql: str) -> pd.DataFrame:
        """
        Execute a validated SELECT query and return results as a DataFrame.
        Enforces MAX_ROWS limit and read-only mode.
        """
        valid, err = NL2SQL.validate(sql)
        if not valid:
            raise ValueError(f"Invalid SQL: {err}")

        try:
            with self.engine.connect() as conn:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                df = pd.read_sql(text(sql), conn)
                if len(df) > MAX_ROWS:
                    logger.warning("Result capped at %d rows (got %d)", MAX_ROWS, len(df))
                    df = df.head(MAX_ROWS)
                return df
        except SQLAlchemyError as e:
            logger.error("SQL execution error: %s", e)
            raise RuntimeError(f"Query failed: {e}") from e

    def get_schema(self, tables: list[str] | None = None) -> str:
        """
        Introspect database schema and return a compact text representation.
        Optionally filter to specific tables.
        """
        schema_query = """
        SELECT
            t.table_name,
            c.column_name,
            c.data_type,
            c.is_nullable
        FROM information_schema.tables t
        JOIN information_schema.columns c ON t.table_name = c.table_name
        WHERE t.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_name, c.ordinal_position
        """
        try:
            df = self.execute(schema_query)
            if tables:
                df = df[df["table_name"].isin(tables)]

            lines = []
            for table, group in df.groupby("table_name"):
                cols = ", ".join(
                    f"{r['column_name']} {r['data_type']}" for _, r in group.iterrows()
                )
                lines.append(f"TABLE {table} ({cols})")
            return "\n".join(lines)
        except Exception:
            return "Schema unavailable"

    def get_preview(self, table: str, limit: int = 3) -> str:
        """Get a short preview of a table for context."""
        try:
            df = self.execute(f"SELECT * FROM {table} LIMIT {limit}")
            return df.to_string(index=False, max_cols=8)
        except Exception:
            return ""
