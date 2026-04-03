"""
backend/analyst.py — Natural-language to SQL engine powered by Google Gemini.
"""

import os
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def _sanitize_sql(sql: str) -> str:
    """Strip markdown fences and return clean SQL."""
    sql = re.sub(r"```(?:sql)?", "", sql, flags=re.IGNORECASE).strip()
    sql = sql.strip("`").strip()
    return sql


def nl_to_sql(
    question: str,
    schema: str,
    model_name: str = "gemini-1.5-flash",
) -> str:
    """
    Convert a natural-language question to a PostgreSQL query using Gemini.

    Args:
        question: Plain-English question from the user.
        schema: Database schema DDL or description string.
        model_name: Gemini model identifier.

    Returns:
        Clean SQL string ready for execution.

    Raises:
        RuntimeError: If the model fails or returns empty output.
    """
    import google.generativeai as genai  # type: ignore

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable not set.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    prompt = f"""You are an expert PostgreSQL engineer.
Given the following database schema:
{schema}

Convert this question to a valid PostgreSQL query:
"{question}"

Rules:
- Return ONLY the SQL. No explanation, no markdown fences.
- Use proper PostgreSQL syntax.
- Prevent SQL injection: do not include user-controlled strings in the query literals.
- If the question cannot be answered with the schema, return: SELECT 'insufficient schema' AS error;
"""

    response = model.generate_content(prompt)
    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")

    sql = _sanitize_sql(response.text)
    logger.info("Generated SQL: %s", sql[:120])
    return sql


def explain_query(sql: str, model_name: str = "gemini-1.5-flash") -> str:
    """Return a plain-English explanation of a SQL query."""
    import google.generativeai as genai  # type: ignore

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable not set.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    prompt = f"Explain the following SQL query in plain English, in 2–3 sentences:\n\n{sql}"
    response = model.generate_content(prompt)
    return response.text.strip() if response.text else "Could not generate explanation."
