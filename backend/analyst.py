"""
backend/analyst.py — Natural-language to SQL engine powered by Google Gemini.

Enhanced with:
  - safety_check(sql)      : validates SQL is read-only
  - format_sql(sql)        : cleans up whitespace/formatting in generated SQL
  - estimate_complexity(sql): rates complexity as 'simple'|'medium'|'complex'
"""

import os
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sanitize_sql(sql: str) -> str:
    """Strip markdown fences and return clean SQL."""
    sql = re.sub(r"```(?:sql)?", "", sql, flags=re.IGNORECASE).strip()
    sql = sql.strip("`").strip()
    return sql


# ---------------------------------------------------------------------------
# Public utility functions
# ---------------------------------------------------------------------------

def safety_check(sql: str) -> Tuple[bool, str]:
    """
    Validate that a SQL string is read-only (SELECT only).

    Args:
        sql: The SQL query string to validate.

    Returns:
        A tuple (is_safe: bool, reason: str).
        If is_safe is True, reason is 'OK'.
        If is_safe is False, reason describes the unsafe keyword found.

    Examples:
        >>> safety_check("SELECT id FROM users")
        (True, 'OK')
        >>> safety_check("DROP TABLE users")
        (False, "Dangerous SQL keyword detected: DROP")
    """
    upper = sql.strip().upper()
    dangerous_keywords = (
        "DROP", "DELETE", "TRUNCATE", "INSERT",
        "UPDATE", "ALTER", "CREATE", "GRANT", "REVOKE",
    )
    for kw in dangerous_keywords:
        if upper.startswith(kw) or f" {kw} " in upper or f"\n{kw} " in upper:
            reason = f"Dangerous SQL keyword detected: {kw}"
            logger.warning("safety_check failed — %s", reason)
            return False, reason

    if not upper.lstrip().startswith("SELECT") and not upper.lstrip().startswith("WITH"):
        reason = "Query does not start with SELECT or WITH (CTE)."
        logger.warning("safety_check failed — %s", reason)
        return False, reason

    logger.debug("safety_check passed for SQL: %s", sql[:80])
    return True, "OK"


def format_sql(sql: str) -> str:
    """
    Clean up whitespace and basic formatting in a generated SQL string.

    Normalises:
    - Multiple consecutive blank lines → single blank line
    - Trailing whitespace on each line
    - Common SQL keyword capitalisation (SELECT, FROM, WHERE, …)
    - Removes surrounding markdown fences if present

    Args:
        sql: Raw SQL string (possibly with markdown fences or inconsistent casing).

    Returns:
        Cleaned SQL string.

    Example:
        >>> format_sql("  select   id,name  from  users  where id=1  ")
        'SELECT id,name FROM users WHERE id=1'
    """
    # Strip markdown fences
    sql = re.sub(r"```(?:sql)?", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"```", "", sql)
    sql = sql.strip("`").strip()

    # Capitalise main SQL keywords that appear as whole words
    keywords = [
        "SELECT", "FROM", "WHERE", "JOIN", "LEFT JOIN", "RIGHT JOIN",
        "INNER JOIN", "OUTER JOIN", "FULL JOIN", "CROSS JOIN",
        "ON", "AND", "OR", "NOT", "IN", "IS", "NULL",
        "GROUP BY", "ORDER BY", "HAVING", "LIMIT", "OFFSET",
        "DISTINCT", "AS", "CASE", "WHEN", "THEN", "ELSE", "END",
        "UNION", "INTERSECT", "EXCEPT", "WITH", "INSERT", "UPDATE",
        "DELETE", "CREATE", "DROP", "ALTER", "COUNT", "SUM", "AVG",
        "MIN", "MAX", "COALESCE", "NULLIF", "CAST", "BETWEEN",
    ]
    for kw in sorted(keywords, key=len, reverse=True):
        # Replace case-insensitive whole-word matches with uppercase
        sql = re.sub(
            r"(?<!\w)" + re.escape(kw) + r"(?!\w)",
            kw,
            sql,
            flags=re.IGNORECASE,
        )

    # Collapse multiple spaces (but not newlines) into a single space
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in sql.splitlines()]

    # Remove consecutive blank lines
    result_lines: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result_lines.append(line)
        prev_blank = is_blank

    formatted = "\n".join(result_lines).strip()
    logger.debug("format_sql output: %s", formatted[:120])
    return formatted


def estimate_complexity(sql: str) -> str:
    """
    Estimate the complexity of a SQL query based on keyword analysis.

    Scoring:
    - +1 per JOIN (any kind)
    - +1 for subquery (nested SELECT)
    - +1 for GROUP BY
    - +1 for HAVING
    - +1 for UNION / INTERSECT / EXCEPT
    - +1 for window functions (OVER)
    - +1 for CTE (WITH … AS)
    - +1 for CASE … WHEN

    Thresholds:
    - 0–1 signals  → 'simple'
    - 2–3 signals  → 'medium'
    - 4+  signals  → 'complex'

    Args:
        sql: SQL query string to analyse.

    Returns:
        One of: 'simple', 'medium', 'complex'.

    Examples:
        >>> estimate_complexity("SELECT id FROM users WHERE id = 1")
        'simple'
        >>> estimate_complexity("SELECT u.name, COUNT(o.id) FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.name")
        'medium'
    """
    upper = sql.upper()
    score = 0

    # Each JOIN type counts separately but we cap at 3 for joins
    join_count = len(re.findall(r"\bJOIN\b", upper))
    score += min(join_count, 3)

    # Nested SELECT = subquery
    selects = len(re.findall(r"\bSELECT\b", upper))
    if selects > 1:
        score += 1

    if re.search(r"\bGROUP\s+BY\b", upper):
        score += 1
    if re.search(r"\bHAVING\b", upper):
        score += 1
    if re.search(r"\b(UNION|INTERSECT|EXCEPT)\b", upper):
        score += 1
    if re.search(r"\bOVER\s*\(", upper):          # window functions
        score += 1
    if re.search(r"\bWITH\b", upper):             # CTE
        score += 1
    if re.search(r"\bCASE\b", upper):
        score += 1

    if score <= 1:
        complexity = "simple"
    elif score <= 3:
        complexity = "medium"
    else:
        complexity = "complex"

    logger.debug("estimate_complexity score=%d → %s for SQL: %s", score, complexity, sql[:80])
    return complexity


# ---------------------------------------------------------------------------
# Core NL→SQL and explanation functions
# ---------------------------------------------------------------------------

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
    """
    Return a plain-English explanation of a SQL query.

    Args:
        sql: SQL query string to explain.
        model_name: Gemini model identifier.

    Returns:
        Plain-English explanation (2–3 sentences).
    """
    import google.generativeai as genai  # type: ignore

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable not set.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    prompt = f"Explain the following SQL query in plain English, in 2–3 sentences:\n\n{sql}"
    response = model.generate_content(prompt)
    return response.text.strip() if response.text else "Could not generate explanation."
