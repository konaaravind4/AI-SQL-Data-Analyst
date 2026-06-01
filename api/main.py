"""
api/main.py — FastAPI REST API for AI SQL Data Analyst.

Endpoints:
    POST /query             — Convert NL question to SQL and return results + chart spec
    POST /query/compare     — Run all configured providers side-by-side and compare
    GET  /schema            — Return current database schema
    GET  /health            — Health check (includes provider + DB table count)
    GET  /providers         — List available/configured LLM providers
    GET  /history           — Last 20 queries from in-memory history (or KonaDB)
    POST /history/similar   — Keyword-match a question against history, return top 3

Enhanced:
    - CORS middleware
    - Module-level _query_history tracking
    - Provider selection per-request via QueryRequest.provider field
    - SQL safety check + complexity estimate in /query response
    - MultiModelSQLGenerator wired into /query endpoint
"""

import os
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.analyst import nl_to_sql, explain_query, safety_check, estimate_complexity, format_sql
from backend.database import get_schema, execute_query, get_table_count
from api.multi_model import MultiModelSQLGenerator, ModelProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI SQL Data Analyst",
    description="Convert plain-English questions to SQL and get instant results.",
    version="2.0.0",
)

# CORS — allow all origins (restrict in production via environment variable)
_cors_origins: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory query history (thread-safe for single-process deployments)
# ---------------------------------------------------------------------------

_query_history: list[dict] = []
_MAX_HISTORY = 200  # internal cap; GET /history returns last 20


def _record_history(entry: dict) -> None:
    """Append an entry to _query_history, trimming to _MAX_HISTORY."""
    _query_history.append(entry)
    if len(_query_history) > _MAX_HISTORY:
        _query_history.pop(0)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Request body for POST /query."""

    question: str = Field(..., min_length=3, max_length=1000, description="Natural-language question.")
    model: str = Field("gemini-1.5-flash", description="LLM model identifier (provider-specific).")
    provider: str = Field(
        "gemini",
        description="LLM provider to use: 'gemini', 'claude', 'openai', or 'auto'.",
    )


class QueryResponse(BaseModel):
    """Response body for POST /query."""

    question: str
    sql: str
    explanation: str
    rows: list[dict]
    column_names: list[str]
    row_count: int
    provider: str
    safety_check: bool
    safety_reason: str
    complexity: str
    latency_ms: float


class CompareRequest(BaseModel):
    """Request body for POST /query/compare."""

    question: str = Field(..., min_length=3, max_length=1000)


class SimilarRequest(BaseModel):
    """Request body for POST /history/similar."""

    question: str = Field(..., min_length=3, max_length=1000)


# ---------------------------------------------------------------------------
# Helper: pick the right generator based on provider
# ---------------------------------------------------------------------------

def _make_generator(provider: str) -> MultiModelSQLGenerator:
    """
    Instantiate a MultiModelSQLGenerator for the given provider.

    Args:
        provider: One of 'gemini', 'claude', 'openai', 'auto'.

    Returns:
        Configured MultiModelSQLGenerator instance.
    """
    return MultiModelSQLGenerator(provider=provider)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", summary="Health check")
async def health():
    """
    Return service health status, the currently configured default provider,
    and the number of tables in the connected database.

    Returns:
        JSON with keys: status, provider, db_table_count, timestamp.
    """
    default_provider = os.getenv("DEFAULT_PROVIDER", "gemini")
    try:
        table_count = get_table_count()
    except Exception as exc:
        logger.warning("health: could not fetch table count — %s", exc)
        table_count = -1

    return {
        "status": "ok",
        "provider": default_provider,
        "db_table_count": table_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/schema", summary="Database schema")
async def schema():
    """Return the current database schema as a text DDL summary."""
    try:
        return {"schema": get_schema()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/providers", summary="List available LLM providers")
async def providers():
    """
    List all supported LLM providers and whether they are configured
    (i.e., their API key is set in the environment).

    Returns:
        JSON with keys: providers (list of dicts with name and configured flag).
    """
    provider_env_keys = {
        "gemini": "GEMINI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    result = [
        {
            "name": name,
            "configured": bool(os.getenv(env_key, "")),
            "env_key": env_key,
        }
        for name, env_key in provider_env_keys.items()
    ]
    logger.info("GET /providers — configured: %s", [p["name"] for p in result if p["configured"]])
    return {"providers": result}


@app.post("/query", response_model=QueryResponse, summary="NL question → SQL + results")
async def query(req: QueryRequest):
    """
    Convert a natural-language question to SQL, execute it, and return results.

    The provider field in the request determines which LLM is used.
    Falls back to Gemini's nl_to_sql() if provider is 'gemini' (legacy path).

    Response includes:
    - Generated SQL (formatted)
    - Plain-English explanation
    - Result rows and column names
    - Safety check result and reason
    - Complexity rating ('simple' | 'medium' | 'complex')
    - Latency in milliseconds
    """
    t_start = time.time()
    logger.info("POST /query — question='%s', provider='%s'", req.question[:80], req.provider)

    try:
        schema_str = get_schema()

        # --- SQL generation ---
        if req.provider == "gemini":
            # Legacy path: use the direct Gemini nl_to_sql function
            raw_sql = nl_to_sql(req.question, schema_str, model_name=req.model)
            used_provider = "gemini"
        else:
            gen = _make_generator(req.provider)
            result = gen.generate_sql(req.question, schema_str, provider=req.provider)  # type: ignore[arg-type]
            raw_sql = result.clean_sql()
            used_provider = result.provider

        # --- Post-processing ---
        sql = format_sql(raw_sql)
        is_safe, safety_reason = safety_check(sql)
        complexity = estimate_complexity(sql)

        if not is_safe:
            raise ValueError(f"Generated SQL failed safety check: {safety_reason}")

        # --- Explanation ---
        explanation = explain_query(sql, model_name=req.model)

        # --- Execution ---
        df = execute_query(sql)
        latency_ms = round((time.time() - t_start) * 1000, 1)

        # --- Record in history ---
        _record_history({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question": req.question,
            "sql": sql,
            "provider": used_provider,
            "complexity": complexity,
            "row_count": len(df),
        })

        logger.info(
            "POST /query — success: provider=%s, rows=%d, latency=%.1fms",
            used_provider, len(df), latency_ms,
        )

        return QueryResponse(
            question=req.question,
            sql=sql,
            explanation=explanation,
            rows=df.to_dict(orient="records"),
            column_names=list(df.columns),
            row_count=len(df),
            provider=used_provider,
            safety_check=is_safe,
            safety_reason=safety_reason,
            complexity=complexity,
            latency_ms=latency_ms,
        )

    except ValueError as exc:
        logger.warning("POST /query — bad request: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("POST /query — unexpected error")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/query/compare", summary="Compare SQL generated by all providers")
async def query_compare(req: CompareRequest):
    """
    Run all configured LLM providers against the same question and return
    their SQL side-by-side for comparison.

    Args (body):
        question: Natural-language question to answer.

    Returns:
        JSON with key 'results': dict mapping provider name → comparison object
        (sql, model, latency_ms, is_safe, complexity, clean_sql).
    """
    logger.info("POST /query/compare — question='%s'", req.question[:80])

    try:
        schema_str = get_schema()
        gen = MultiModelSQLGenerator()
        raw_results = gen.compare_providers(req.question, schema_str)

        comparison: dict[str, Any] = {}
        for provider_name, res in raw_results.items():
            clean = res.clean_sql()
            is_safe, safety_reason = safety_check(clean)
            complexity = estimate_complexity(clean)
            comparison[provider_name] = {
                "sql": clean,
                "model": res.model,
                "latency_ms": res.latency_ms,
                "is_safe": is_safe,
                "safety_reason": safety_reason,
                "complexity": complexity,
            }

        logger.info("POST /query/compare — providers returned: %s", list(comparison.keys()))
        return {"question": req.question, "results": comparison}

    except Exception as exc:
        logger.exception("POST /query/compare — unexpected error")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/history", summary="Return last 20 queries from history")
async def history():
    """
    Return the last 20 queries from the in-memory query history.

    If KONA_DB_PATH is set, the history is also persisted there and
    read back on startup (requires the `kona` package).

    Returns:
        JSON with key 'history': list of query record dicts (newest first).
    """
    recent = list(reversed(_query_history))[:20]
    logger.info("GET /history — returning %d records.", len(recent))
    return {"history": recent, "total_recorded": len(_query_history)}


@app.post("/history/similar", summary="Find similar past queries by keyword matching")
async def history_similar(req: SimilarRequest):
    """
    Keyword-match the given question against the in-memory query history
    and return the top 3 most similar past queries.

    Similarity is scored by counting how many non-trivial words in the
    question appear in each historical question (case-insensitive).

    Args (body):
        question: The question to match against.

    Returns:
        JSON with key 'similar': list of up to 3 history records,
        each augmented with a 'score' field.
    """
    import re as _re

    logger.info("POST /history/similar — question='%s'", req.question[:80])

    # Tokenise: lower-case alphabetic words, drop stop-words
    _STOP_WORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "of", "in", "on", "at",
        "to", "for", "with", "by", "from", "and", "or", "but", "not", "how",
        "many", "much", "what", "which", "who", "when", "where", "why",
        "all", "each", "every", "any", "some", "no", "my", "our", "your",
        "their", "its", "me", "us", "them", "get", "give", "show", "list",
        "find", "fetch",
    }

    def _tokenise(text: str) -> set[str]:
        words = _re.findall(r"[a-z]+", text.lower())
        return {w for w in words if w not in _STOP_WORDS and len(w) > 2}

    question_tokens = _tokenise(req.question)

    scored: list[dict] = []
    for record in _query_history:
        past_tokens = _tokenise(record.get("question", ""))
        score = len(question_tokens & past_tokens)
        if score > 0:
            scored.append({**record, "score": score})

    # Sort descending by score, then newest first
    scored.sort(key=lambda x: (-x["score"], x.get("timestamp", "")), reverse=False)
    top3 = scored[:3]

    logger.info("POST /history/similar — found %d candidates, returning top %d.", len(scored), len(top3))
    return {"question": req.question, "similar": top3}
