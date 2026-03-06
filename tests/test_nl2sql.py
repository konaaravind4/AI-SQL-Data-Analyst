"""
Tests for AI SQL Data Analyst — NL2SQL validation, visualizer type detection.
"""
from __future__ import annotations

import pytest
import pandas as pd
from unittest.mock import MagicMock, patch


class TestNL2SQL:
    def test_validate_select_ok(self):
        from backend.nl2sql import NL2SQL
        valid, err = NL2SQL.validate("SELECT * FROM orders LIMIT 100")
        assert valid is True
        assert err is None

    def test_validate_rejects_drop(self):
        from backend.nl2sql import NL2SQL
        valid, err = NL2SQL.validate("DROP TABLE users")
        assert valid is False
        assert err is not None

    def test_validate_rejects_delete(self):
        from backend.nl2sql import NL2SQL
        valid, err = NL2SQL.validate("DELETE FROM logs WHERE date < '2020-01-01'")
        assert valid is False

    def test_validate_rejects_non_select(self):
        from backend.nl2sql import NL2SQL
        valid, err = NL2SQL.validate("INSERT INTO users VALUES (1, 'test')")
        assert valid is False

    def test_is_safe_returns_true_for_select(self):
        from backend.nl2sql import NL2SQL
        assert NL2SQL.is_safe("SELECT id, name FROM users WHERE active = true") is True

    def test_is_safe_returns_false_for_exec(self):
        from backend.nl2sql import NL2SQL
        assert NL2SQL.is_safe("EXEC sp_msforeachtable 'DROP TABLE ?'") is False

    @patch("backend.nl2sql.genai")
    def test_convert_strips_markdown(self, mock_genai):
        from backend.nl2sql import NL2SQL

        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content.return_value.text = "```sql\nSELECT 1\n```"

        converter = NL2SQL()
        result = converter.convert("What is 1?", "TABLE test (id INT)")
        assert result == "SELECT 1"
        assert "```" not in result


class TestVisualizer:
    def test_detect_bar_chart(self):
        from backend.visualizer import Visualizer
        df = pd.DataFrame({"category": ["A", "B", "C"], "revenue": [100, 200, 150]})
        viz = Visualizer()
        chart_type = viz._detect_chart_type(df)
        assert chart_type in ("bar", "pie")

    def test_detect_time_series(self):
        from backend.visualizer import Visualizer
        df = pd.DataFrame({
            "date": ["2024-01-01", "2024-01-02"],
            "sales": [1000, 1200]
        })
        viz = Visualizer()
        chart_type = viz._detect_chart_type(df)
        assert chart_type in ("area", "line")

    def test_render_empty_dataframe(self):
        from backend.visualizer import Visualizer
        import plotly.graph_objects as go
        viz = Visualizer()
        fig = viz.render(pd.DataFrame(), title="Empty Test")
        assert isinstance(fig, go.Figure)

    def test_render_bar_chart(self):
        from backend.visualizer import Visualizer
        import plotly.graph_objects as go
        df = pd.DataFrame({"product": ["A", "B"], "unit_sold": [300, 150]})
        viz = Visualizer()
        fig = viz.render(df, chart_type="bar")
        assert isinstance(fig, go.Figure)
