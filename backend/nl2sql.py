"""
Natural language to SQL converter using Google Gemini with schema-aware prompting.
Includes SQL injection prevention and query explanation.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
FORBIDDEN_PATTERNS = re.compile(
    r"\b(DROP|TRUNCATE|DELETE|UPDATE|INSERT|ALTER|CREATE|GRANT|REVOKE|EXEC|EXECUTE)\b",
    re.IGNORECASE,
)


class NL2SQL:
    """
    Converts natural language business questions to PostgreSQL queries
    using schema-aware few-shot prompting with Gemini 1.5 Flash.
    """

    SYSTEM_PROMPT = """You are an expert PostgreSQL data analyst.
Given a database schema and a natural language question, generate a valid PostgreSQL query.
Rules:
- Return ONLY the SQL query, no explanation, no markdown, no backticks.
- Use proper aliases for readability.
- Add LIMIT 1000 to SELECT queries unless the user specifies a count.
- Never generate INSERT, UPDATE, DELETE, DROP, or DDL statements.
- Use date_trunc() for time-based grouping.
- Default to current month if no time range specified."""

    def __init__(self, model: str = "gemini-1.5-flash"):
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            model,
            system_instruction=self.SYSTEM_PROMPT,
        )

    def convert(self, question: str, schema: str) -> str:
        """Convert a natural language question to a PostgreSQL query."""
        prompt = f"""Database Schema:
{schema}

Question: {question}

PostgreSQL Query:"""
        response = self.model.generate_content(prompt)
        sql = response.text.strip()
        # Strip any accidentally included markdown
        sql = re.sub(r"^```sql\n?|^```\n?|\n?```$", "", sql, flags=re.MULTILINE).strip()
        return sql

    def explain(self, sql: str, results_preview: str = "") -> str:
        """Generate a plain English explanation of a SQL query and its results."""
        prompt = f"""Explain this SQL query in plain English (2-3 sentences max):
{sql}

{f"Results preview: {results_preview}" if results_preview else ""}

Explain in simple terms for a non-technical business user:"""
        response = self.model.generate_content(prompt)
        return response.text.strip()

    @staticmethod
    def is_safe(sql: str) -> bool:
        """Check that SQL doesn't contain mutating or dangerous statements."""
        return not bool(FORBIDDEN_PATTERNS.search(sql))

    @staticmethod
    def validate(sql: str) -> tuple[bool, Optional[str]]:
        """
        Basic SQL validation:
        Returns (is_valid, error_message).
        """
        sql_stripped = sql.strip().upper()
        if not sql_stripped.startswith("SELECT"):
            return False, "Only SELECT queries are permitted."
        if FORBIDDEN_PATTERNS.search(sql):
            return False, "Query contains forbidden SQL operations."
        if not sql_stripped:
            return False, "Empty query."
        return True, None
