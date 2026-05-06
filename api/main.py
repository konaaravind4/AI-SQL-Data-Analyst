"""
api/main.py — FastAPI REST API for AI SQL Data Analyst.

Endpoints:
    POST /query     — Convert NL question to SQL and return results + chart spec
    GET  /schema    — Return current database schema
    GET  /health    — Health check
"""

import os
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Any

from backend.analyst import nl_to_sql, explain_query
from backend.database import get_schema, execute_query

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI SQL Data Analyst",
    description="Convert plain-English questions to SQL and get instant results.",
    version="1.0.0",
)


#Schemas

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    model: str = Field("gemini-1.5-flash")


class QueryResponse(BaseModel):
    question: str
    sql: str
    explanation: str
    rows: list[dict]
    column_names: list[str]
    row_count: int


# Endpoints

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/schema")
async def schema():
    try:
        return {"schema": get_schema()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    try:
        schema_str = get_schema()
        sql = nl_to_sql(req.question, schema_str, model_name=req.model)
        explanation = explain_query(sql, model_name=req.model)
        df = execute_query(sql)
        return QueryResponse(
            question=req.question,
            sql=sql,
            explanation=explanation,
            rows=df.to_dict(orient="records"),
            column_names=list(df.columns),
            row_count=len(df),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Query processing failed")
        raise HTTPException(status_code=500, detail=str(exc))
