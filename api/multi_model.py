"""
Multi-Model Support for AI SQL Data Analyst
============================================
Allows switching between Gemini, Claude (Anthropic), and OpenAI GPT
for SQL generation — enabling model comparison and fallback chains.

Usage:
    from api.multi_model import MultiModelSQLGenerator, ModelProvider

    gen = MultiModelSQLGenerator(provider="gemini")
    sql = gen.generate_sql(question="How many users signed up this week?", schema=schema)

    # Try all providers and pick best result
    best = gen.generate_with_fallback(question, schema)
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Literal

ModelProvider = Literal["gemini", "claude", "openai", "auto"]

_SYSTEM_PROMPT = """You are an expert SQL query generator. Given a database schema and a natural language question, generate a correct, optimized, read-only PostgreSQL SQL query.

Rules:
1. Generate ONLY a SELECT query — never INSERT, UPDATE, DELETE, DROP, or any DDL.
2. Use explicit column names — avoid SELECT *.
3. Add appropriate indexes hints as SQL comments if beneficial.
4. Return ONLY the SQL query, no explanation, no markdown code blocks.
5. Use standard PostgreSQL syntax.
6. Ensure the query is safe from SQL injection (no dynamic table/column names from user input).
"""


@dataclass
class SQLGenerationResult:
    sql: str
    provider: str
    latency_ms: float
    model: str
    confidence: float = 1.0   # model self-assessed confidence (if available)

    @property
    def is_safe(self) -> bool:
        """Check that the query is read-only (SELECT only)."""
        stripped = self.sql.strip().upper()
        return stripped.startswith("SELECT") and not any(
            kw in stripped for kw in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]
        )

    def clean_sql(self) -> str:
        """Remove markdown code fences if model wrapped in ```sql ... ```"""
        sql = re.sub(r"```sql\s*", "", self.sql)
        sql = re.sub(r"```\s*", "", sql)
        return sql.strip()


class MultiModelSQLGenerator:
    """
    SQL generator with support for multiple LLM providers.

    Providers:
    - gemini: Google Gemini (gemini-1.5-flash, gemini-2.0-flash)
    - claude: Anthropic Claude (claude-3-5-haiku)
    - openai: OpenAI GPT-4o-mini
    - auto:   Try providers in order, use first successful result

    Args:
        provider: Default provider to use.
        gemini_api_key: Gemini API key (or from GEMINI_API_KEY env).
        anthropic_api_key: Claude API key (or from ANTHROPIC_API_KEY env).
        openai_api_key: OpenAI API key (or from OPENAI_API_KEY env).
    """

    def __init__(
        self,
        provider: ModelProvider = "gemini",
        gemini_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
    ):
        self.provider = provider
        self._keys = {
            "gemini": gemini_api_key or os.getenv("GEMINI_API_KEY", ""),
            "claude": anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", ""),
            "openai": openai_api_key or os.getenv("OPENAI_API_KEY", ""),
        }

    def generate_sql(
        self,
        question: str,
        schema: str,
        provider: ModelProvider | None = None,
    ) -> SQLGenerationResult:
        """
        Generate SQL from a natural language question.

        Args:
            question: Natural language business question.
            schema: Database schema description (CREATE TABLE statements or column list).
            provider: Override the default provider for this call.

        Returns:
            SQLGenerationResult with the generated SQL and metadata.

        Example:
            >>> result = gen.generate_sql(
            ...     question="How many orders were placed yesterday?",
            ...     schema="orders(id INT, user_id INT, amount FLOAT, created_at TIMESTAMP)"
            ... )
            >>> print(result.clean_sql())
        """
        p = provider or self.provider
        if p == "auto":
            return self.generate_with_fallback(question, schema)

        fn = {
            "gemini": self._generate_gemini,
            "claude": self._generate_claude,
            "openai": self._generate_openai,
        }.get(p, self._generate_gemini)

        return fn(question, schema)

    def generate_with_fallback(
        self,
        question: str,
        schema: str,
        order: list[str] | None = None,
    ) -> SQLGenerationResult:
        """
        Try providers in order and return the first successful result.

        Args:
            question: Natural language question.
            schema: Database schema.
            order: Provider order (default: ["gemini", "claude", "openai"]).

        Returns:
            First successful SQLGenerationResult.
        """
        providers = order or ["gemini", "claude", "openai"]
        last_err = None
        for p in providers:
            try:
                result = self.generate_sql(question, schema, provider=p)
                if result.sql and result.is_safe:
                    return result
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"All providers failed. Last error: {last_err}")

    def _prompt(self, question: str, schema: str) -> str:
        return (
            f"Schema:\n{schema}\n\n"
            f"Question: {question}\n\n"
            f"Generate the SQL query:"
        )

    def _generate_gemini(self, question: str, schema: str) -> SQLGenerationResult:
        import google.generativeai as genai
        genai.configure(api_key=self._keys["gemini"])
        model = genai.GenerativeModel(
            "gemini-2.0-flash",
            system_instruction=_SYSTEM_PROMPT,
        )
        start = time.time()
        resp = model.generate_content(self._prompt(question, schema))
        elapsed = (time.time() - start) * 1000
        return SQLGenerationResult(
            sql=resp.text.strip(),
            provider="gemini",
            model="gemini-2.0-flash",
            latency_ms=round(elapsed, 1),
        )

    def _generate_claude(self, question: str, schema: str) -> SQLGenerationResult:
        import anthropic
        client = anthropic.Anthropic(api_key=self._keys["claude"])
        start = time.time()
        msg = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._prompt(question, schema)}],
        )
        elapsed = (time.time() - start) * 1000
        sql = msg.content[0].text.strip() if msg.content else ""
        return SQLGenerationResult(
            sql=sql,
            provider="claude",
            model="claude-3-5-haiku",
            latency_ms=round(elapsed, 1),
        )

    def _generate_openai(self, question: str, schema: str) -> SQLGenerationResult:
        from openai import OpenAI
        client = OpenAI(api_key=self._keys["openai"])
        start = time.time()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": self._prompt(question, schema)},
            ],
            max_tokens=512,
            temperature=0,
        )
        elapsed = (time.time() - start) * 1000
        sql = resp.choices[0].message.content.strip()
        return SQLGenerationResult(
            sql=sql,
            provider="openai",
            model="gpt-4o-mini",
            latency_ms=round(elapsed, 1),
        )

    def compare_providers(
        self,
        question: str,
        schema: str,
    ) -> dict[str, SQLGenerationResult]:
        """
        Run all configured providers and return results for comparison.

        Returns:
            Dict mapping provider name → SQLGenerationResult.
        """
        results = {}
        for provider in ["gemini", "claude", "openai"]:
            if not self._keys.get(provider):
                continue
            try:
                results[provider] = self.generate_sql(question, schema, provider=provider)
            except Exception as e:
                results[provider] = SQLGenerationResult(
                    sql=f"ERROR: {e}", provider=provider, model="", latency_ms=0
                )
        return results
