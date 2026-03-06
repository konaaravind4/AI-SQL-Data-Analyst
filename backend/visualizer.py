"""
Automatic Plotly chart selection based on DataFrame structure.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

logger = logging.getLogger(__name__)


class Visualizer:
    """
    Automatically selects and renders the best chart type for a given DataFrame.

    Heuristics:
    - 1 categorical + 1 numeric → bar chart
    - 1 date/time + 1 numeric → area/line chart
    - 2 numeric columns → scatter
    - Many rows, 1 numeric → histogram
    - Aggregated counts → pie (if ≤ 10 categories)
    """

    CHART_TYPES = [
        "auto", "bar", "line", "area", "scatter",
        "pie", "histogram", "heatmap", "box", "table"
    ]

    def render(
        self,
        df: pd.DataFrame,
        chart_type: str = "auto",
        title: str = "Query Results",
    ) -> go.Figure:
        """Generate a Plotly figure for the given DataFrame."""
        if df.empty:
            return self._empty_chart(title)

        if chart_type == "auto":
            chart_type = self._detect_chart_type(df)

        logger.info("Rendering chart type: %s (%d rows)", chart_type, len(df))

        numeric = df.select_dtypes(include="number").columns.tolist()
        categorical = df.select_dtypes(include=["object", "category"]).columns.tolist()
        date_cols = [c for c in df.columns if "date" in c.lower() or "time" in c.lower() or "month" in c.lower()]

        try:
            if chart_type == "bar" and categorical and numeric:
                fig = px.bar(df, x=categorical[0], y=numeric[0], title=title, text_auto=True)
            elif chart_type in ("line", "area") and date_cols and numeric:
                x_col = date_cols[0]
                if chart_type == "area":
                    fig = px.area(df, x=x_col, y=numeric[0], title=title)
                else:
                    fig = px.line(df, x=x_col, y=numeric[0], title=title, markers=True)
            elif chart_type == "scatter" and len(numeric) >= 2:
                color = categorical[0] if categorical else None
                fig = px.scatter(df, x=numeric[0], y=numeric[1], color=color, title=title)
            elif chart_type == "pie" and categorical and numeric:
                fig = px.pie(df, names=categorical[0], values=numeric[0], title=title)
            elif chart_type == "histogram" and numeric:
                fig = px.histogram(df, x=numeric[0], title=title)
            elif chart_type == "box" and categorical and numeric:
                fig = px.box(df, x=categorical[0], y=numeric[0], title=title)
            elif chart_type == "heatmap" and len(numeric) >= 2:
                pivot = df.pivot_table(index=categorical[0], columns=categorical[1], values=numeric[0]) if len(categorical) >= 2 else df[numeric].corr()
                fig = px.imshow(pivot, title=title, text_auto=True)
            else:
                # Fallback: interactive table
                fig = go.Figure(
                    data=[go.Table(
                        header=dict(values=list(df.columns), fill_color="#1e1e2e", font=dict(color="white")),
                        cells=dict(values=[df[c] for c in df.columns]),
                    )]
                )
                fig.update_layout(title=title)

            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#0f0f1a",
                plot_bgcolor="#0f0f1a",
                font=dict(color="#e2e8f0"),
                margin=dict(l=40, r=40, t=50, b=40),
            )
            return fig

        except Exception as e:
            logger.warning("Chart rendering failed (%s): %s. Falling back to table.", chart_type, e)
            return self._table_chart(df, title)

    def _detect_chart_type(self, df: pd.DataFrame) -> str:
        numeric = df.select_dtypes(include="number").columns
        categorical = df.select_dtypes(include=["object", "category"]).columns
        date_cols = [c for c in df.columns if any(k in c.lower() for k in ["date", "time", "month", "year"])]

        if date_cols and len(numeric) >= 1:
            return "area"
        if len(numeric) >= 2 and len(categorical) == 0:
            return "scatter"
        if len(categorical) >= 1 and len(numeric) >= 1:
            if df[categorical[0]].nunique() <= 10 and "count" in df.columns:
                return "pie"
            if df[categorical[0]].nunique() <= 20:
                return "bar"
        if len(numeric) == 1 and len(df) > 100:
            return "histogram"
        return "bar"

    @staticmethod
    def _empty_chart(title: str) -> go.Figure:
        fig = go.Figure()
        fig.update_layout(title=f"{title} — No results", template="plotly_dark")
        return fig

    @staticmethod
    def _table_chart(df: pd.DataFrame, title: str) -> go.Figure:
        fig = go.Figure(data=[go.Table(
            header=dict(values=list(df.columns)),
            cells=dict(values=[df[c] for c in df.columns]),
        )])
        fig.update_layout(title=title, template="plotly_dark")
        return fig
