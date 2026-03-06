"""
FastAPI REST API for AI SQL Data Analyst.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.nl2sql import NL2SQL
from backend.executor import QueryExecutor
from backend.visualizer import Visualizer

logger = logging.getLogger(__name__)

nl2sql: Optional[NL2SQL] = None
executor: Optional[QueryExecutor] = None
viz = Visualizer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global nl2sql, executor
    nl2sql = NL2SQL()
    executor = QueryExecutor()
    yield


app = FastAPI(title="AI SQL Data Analyst API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    chart_type: str = "auto"
    max_rows: int = Field(100, ge=1, le=10000)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/query")
async def query(req: QueryRequest) -> dict:
    if not nl2sql or not executor:
        raise HTTPException(status_code=503, detail="Service not ready")

    t0 = time.monotonic()

    # Get schema
    try:
        schema = executor.get_schema()
    except Exception:
        schema = "Schema unavailable - use common table names"

    # Generate SQL
    sql = nl2sql.convert(req.question, schema)
    valid, err = NL2SQL.validate(sql)
    if not valid:
        raise HTTPException(status_code=422, detail=f"Generated invalid SQL: {err}")

    # Execute
    try:
        df = executor.execute(sql)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Visualize
    fig = viz.render(df, chart_type=req.chart_type, title=req.question)

    # Explain
    explanation = nl2sql.explain(sql, df.head(3).to_string(index=False) if not df.empty else "")

    import plotly.io as pio
    latency_ms = (time.monotonic() - t0) * 1000

    return {
        "sql": sql,
        "explanation": explanation,
        "row_count": len(df),
        "column_count": len(df.columns),
        "chart_json": pio.to_json(fig),
        "chart_type_used": req.chart_type,
        "latency_ms": round(latency_ms, 1),
        "results": df.head(req.max_rows).to_dict(orient="records"),
    }


@app.get("/schema")
async def get_schema() -> dict:
    if not executor:
        raise HTTPException(status_code=503, detail="Service not ready")
    return {"schema": executor.get_schema()}
