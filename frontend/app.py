"""
Streamlit frontend for AI SQL Data Analyst.
"""
from __future__ import annotations

import os
import sys
import json

import pandas as pd
import streamlit as st
import requests

st.set_page_config(
    page_title="AI SQL Data Analyst",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8002")

# ── Page header ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
body { background-color: #0f0f1a; }
.main-header { font-size: 2.5rem; font-weight: 800; 
    background: linear-gradient(135deg, #667eea, #764ba2); 
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.metric-card { background: #1e1e2e; border-radius: 12px; padding: 1rem; 
    border: 1px solid #313149; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="main-header">🔍 AI SQL Data Analyst</h1>', unsafe_allow_html=True)
st.caption("Ask plain-English questions → get optimized SQL + instant charts")

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    chart_type = st.selectbox(
        "Chart Type",
        ["auto", "bar", "line", "area", "scatter", "pie", "histogram", "table"],
    )
    max_rows = st.slider("Max Rows", 10, 1000, 100)
    show_sql = st.checkbox("Show Generated SQL", value=True)
    show_explanation = st.checkbox("Show AI Explanation", value=True)

    st.divider()
    st.subheader("📋 Example Questions")
    examples = [
        "Show top 10 customers by revenue this month",
        "What are the daily sales for the last 30 days?",
        "Which products have declining sales compared to last quarter?",
        "Show the distribution of order values",
        "What is the average order value by region?",
    ]
    for ex in examples:
        if st.button(ex, use_container_width=True):
            st.session_state["question"] = ex

# ── Main area ─────────────────────────────────────────────────────────────────
col1, col2 = st.columns([3, 1])
with col1:
    question = st.text_input(
        "Ask a business question:",
        value=st.session_state.get("question", ""),
        placeholder="e.g. Show top 5 products by revenue this month",
        key="question_input",
    )
with col2:
    analyse = st.button("🚀 Analyse", type="primary", use_container_width=True)

if analyse and question:
    with st.spinner("Thinking..."):
        try:
            resp = requests.post(
                f"{API_BASE}/query",
                json={"question": question, "chart_type": chart_type, "max_rows": max_rows},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.ConnectionError:
            st.error("⚠️ API server is not running. Please start the FastAPI backend.")
            st.stop()
        except Exception as e:
            st.error(f"Error: {e}")
            st.stop()

    # SQL display
    if show_sql and data.get("sql"):
        with st.expander("📝 Generated SQL", expanded=True):
            st.code(data["sql"], language="sql")

    # Explanation
    if show_explanation and data.get("explanation"):
        st.info(f"💡 **AI Explanation:** {data['explanation']}")

    # Metrics row
    if data.get("row_count") is not None:
        cols = st.columns(4)
        cols[0].metric("Rows Returned", data["row_count"])
        cols[1].metric("Query Time", f"{data.get('latency_ms', 0):.0f}ms")
        cols[2].metric("Columns", data.get("column_count", "—"))
        cols[3].metric("Chart Type", data.get("chart_type_used", "—"))

    # Chart
    if data.get("chart_json"):
        import plotly.io as pio, json as _json
        fig = pio.from_json(data["chart_json"])
        st.plotly_chart(fig, use_container_width=True)

    # Data table
    if data.get("results"):
        with st.expander("📊 Raw Data", expanded=False):
            df = pd.DataFrame(data["results"])
            st.dataframe(df, use_container_width=True)
            csv = df.to_csv(index=False)
            st.download_button("⬇️ Download CSV", csv, "results.csv", "text/csv")
