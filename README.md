# AI SQL Data Analyst 🔍

> **Convert plain-English business questions into optimized SQL queries — now with multi-model support (Gemini + Claude + OpenAI), KonaDB backend, query history with RAG suggestions, and streaming results.**

[![CI](https://github.com/konaaravind4/AI-SQL-Data-Analyst/actions/workflows/ci.yml/badge.svg)](https://github.com/konaaravind4/AI-SQL-Data-Analyst/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![Gemini](https://img.shields.io/badge/gemini-2.0_flash-orange)](https://ai.google.dev)
[![Claude](https://img.shields.io/badge/claude-3.5_haiku-purple)](https://anthropic.com)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Stars](https://img.shields.io/github/stars/konaaravind4/AI-SQL-Data-Analyst?style=social)](https://github.com/konaaravind4/AI-SQL-Data-Analyst)

Convert plain-English business questions into optimized PostgreSQL queries with instant result visualization, powered by **Google Gemini** (with Claude and OpenAI fallback), schema-aware prompting, SQL injection prevention, and full result streaming.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Natural Language → SQL** | Ask in plain English, get accurate SQL |
| **SQL Injection Prevention** | Only SELECT queries allowed, fully validated |
| **Structured Results** | JSON rows + column names + plain explanation |
| **FastAPI REST API** | `/query`, `/schema`, `/health`, `/stream` |
| **Docker-ready** | One-command deployment |
| **🆕 Multi-Model Support** | Gemini + Claude + OpenAI with auto-fallback |
| **🆕 KonaDB Backend** | Use `kona://` instead of PostgreSQL |
| **🆕 Query History + RAG** | Suggest similar past queries using vector search |
| **🆕 Streaming Results** | WebSocket endpoint for large result sets |
| **🆕 Model Comparison** | Run all providers and compare SQL outputs |

---

## 🏗️ Architecture

```
User Question
     │
     ▼
Schema Injection
     │
     ▼
┌────────────────────────────────────┐
│       MultiModelSQLGenerator       │
│  ┌──────────┐ ┌──────┐ ┌───────┐  │
│  │  Gemini  │ │Claude│ │OpenAI │  │
│  └──────────┘ └──────┘ └───────┘  │
│         Auto-fallback chain        │
└────────────────────────────────────┘
     │
     ▼
SQL Validation (SELECT-only guard)
     │
     ▼
┌───────────────────────────────────┐
│           Database Backend         │
│  PostgreSQL  │  KonaDB (kona://)  │
└───────────────────────────────────┘
     │
     ▼
JSON Response + Explanation + History Save
```

---

## 🚀 Quick Start

```bash
git clone https://github.com/konaaravind4/AI-SQL-Data-Analyst
cd AI-SQL-Data-Analyst
cp .env.example .env
# Edit .env with your API keys and DB URL
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

---

## 🐳 Docker

```bash
docker build -t ai-sql-analyst .
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  -e DATABASE_URL=postgresql://user:pass@host:5432/db \
  ai-sql-analyst

# With KonaDB backend (no PostgreSQL needed!)
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  -e DATABASE_URL=kona:///data/mydb.kona \
  -v $(pwd)/data:/data \
  ai-sql-analyst
```

---

## 📡 API Reference

### Query (Single Provider)

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How many users signed up in the last 7 days?",
    "provider": "gemini"
  }'

# Response
{
  "sql": "SELECT COUNT(*) AS new_users FROM users WHERE created_at >= NOW() - INTERVAL '7 days'",
  "rows": [{"new_users": 142}],
  "explanation": "This query counts users who registered in the last 7 days.",
  "provider": "gemini",
  "model": "gemini-2.0-flash",
  "latency_ms": 312
}
```

### Multi-Model Comparison (New!)

```bash
curl -X POST http://localhost:8000/query/compare \
  -d '{"question": "What is the average order value per customer?"}'

# Returns SQL from all providers for comparison:
{
  "gemini": {"sql": "SELECT user_id, AVG(amount) ...", "latency_ms": 280},
  "claude": {"sql": "SELECT user_id, AVG(amount) ...", "latency_ms": 350},
  "openai": {"sql": "SELECT user_id, AVG(amount) ...", "latency_ms": 410}
}
```

### KonaDB Backend (New!)

```bash
# Query KonaDB directly — no PostgreSQL needed
curl -X POST http://localhost:8000/query \
  -d '{
    "question": "Show me the top 5 products by revenue",
    "backend": "kona"
  }'
```

### Query History with RAG Suggestions (New!)

```bash
# Get similar past queries
curl -X POST http://localhost:8000/history/similar \
  -d '{"question": "Show me sales by region"}'

# Response
{
  "similar_queries": [
    {"question": "Revenue breakdown by country", "sql": "SELECT region, SUM(amount)...", "similarity": 0.91},
    {"question": "Monthly sales per territory", "sql": "SELECT territory, ...", "similarity": 0.84}
  ]
}
```

### Schema Exploration

```bash
# Get database schema
curl http://localhost:8000/schema

# Get schema for specific table
curl http://localhost:8000/schema/orders
```

---

## 🧩 Multi-Model Support (New!)

Use any LLM provider or let the system auto-select:

```python
from api.multi_model import MultiModelSQLGenerator

# Use a specific provider
gen = MultiModelSQLGenerator(provider="claude")
result = gen.generate_sql(
    question="What is the retention rate of users from last month?",
    schema="users(id, created_at), sessions(user_id, started_at)"
)
print(result.clean_sql())
print(f"Provider: {result.provider} | Latency: {result.latency_ms}ms")

# Auto-fallback: try Gemini first, then Claude, then OpenAI
gen = MultiModelSQLGenerator(provider="auto")
result = gen.generate_with_fallback(question, schema)

# Compare all providers
comparisons = gen.compare_providers(question, schema)
for provider, result in comparisons.items():
    print(f"{provider}: {result.sql[:80]}... ({result.latency_ms}ms)")
```

---

## 💾 KonaDB Backend (New!)

Use [KonaDB](https://github.com/konaaravind4/kona-db) instead of PostgreSQL — zero infrastructure needed:

```python
# .env
DATABASE_URL=kona:///path/to/mydb.kona

# Works exactly like PostgreSQL — all SQL features supported
```

```bash
# Analyze review history from Code Review Bot (stored in KonaDB)
curl -X POST http://localhost:8000/query \
  -d '{
    "question": "What are the most common security issues in PR reviews this month?",
    "db_path": "reviews.kona"
  }'
```

---

## 🌍 Ecosystem Integration

```
AI-SQL-Data-Analyst
     │
     ├── Query PostgreSQL or KonaDB ──────────────────► Any project's data
     │
     ├── Multi-model (Gemini/Claude/OpenAI) ─────────► Best SQL for any schema
     │
     ├── RAG history suggestions ─────────────────────► RAG-GraphRAG-Knowledge-Engine
     │
     └── Query these datasets in plain English:
           • review_history    (from Agentic-Code-Review-Bot)
           • sentiment_emotions (from Sentiment Dashboard)
           • backtest_results  (from Kronos)
           • kona_timeseries   (from any KonaDB project)
```

---

## 🤝 Related Projects

| Project | Integration |
|---------|-------------|
| [kona-db](https://github.com/konaaravind4/kona-db) | Alternative database backend (`kona://`) |
| [RAG-GraphRAG-Knowledge-Engine](https://github.com/konaaravind4/RAG-GraphRAG-Knowledge-Engine) | Query history similarity suggestions |
| [Agentic-Code-Review-Bot](https://github.com/konaaravind4/Agentic-Code-Review-Bot) | Query review history in natural language |
| [Real-time-Sentiment-Intelligence-Dashboard](https://github.com/konaaravind4/Real-time-Sentiment-Intelligence-Dashboard) | Analyze emotion trends via NL queries |

---

## 📄 License

MIT © [konaaravind4](https://github.com/konaaravind4)
