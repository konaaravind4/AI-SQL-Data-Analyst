"""
tests/test_analyst.py — Unit tests for AI SQL Analyst (no live DB or Gemini needed).
"""

import pytest
from unittest.mock import patch, MagicMock


class TestSanitizeSQL:
    def test_strips_markdown_fence(self):
        from backend.analyst import _sanitize_sql
        assert _sanitize_sql("```sql\nSELECT 1\n```") == "SELECT 1"

    def test_strips_plain_fence(self):
        from backend.analyst import _sanitize_sql
        assert _sanitize_sql("```SELECT 1```") == "SELECT 1"

    def test_passthrough_clean_sql(self):
        from backend.analyst import _sanitize_sql
        sql = "SELECT id, name FROM users WHERE active = true"
        assert _sanitize_sql(sql) == sql


class TestCheckSafeSQL:
    def test_allows_select(self):
        from backend.database import _check_safe_sql
        _check_safe_sql("SELECT * FROM users")  # Should not raise

    def test_blocks_drop(self):
        from backend.database import _check_safe_sql
        with pytest.raises(ValueError, match="DROP"):
            _check_safe_sql("DROP TABLE users")

    def test_blocks_delete(self):
        from backend.database import _check_safe_sql
        with pytest.raises(ValueError, match="DELETE"):
            _check_safe_sql("DELETE FROM users WHERE id=1")

    def test_blocks_insert(self):
        from backend.database import _check_safe_sql
        with pytest.raises(ValueError, match="INSERT"):
            _check_safe_sql("INSERT INTO users VALUES (1,'test')")


class TestNLToSQL:
    @patch("backend.analyst.genai")
    def test_generates_sql(self, mock_genai):
        mock_model = MagicMock()
        mock_model.generate_content.return_value.text = "SELECT COUNT(*) FROM orders"
        mock_genai.GenerativeModel.return_value = mock_model

        from backend.analyst import nl_to_sql
        import os
        os.environ["GEMINI_API_KEY"] = "fake"
        result = nl_to_sql("How many orders?", "TABLE orders (id INT, total FLOAT)")
        assert "SELECT" in result.upper()


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        from fastapi.testclient import TestClient
        import api.main as m
        client = TestClient(m.app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
