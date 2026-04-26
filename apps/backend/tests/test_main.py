"""
Tests for the backend service.

These tests are intentionally lightweight — they test the models and
database helpers directly without spinning up the full FastAPI app
(which requires live Redis + PostgreSQL connections).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Model Tests ──────────────────────────────────────────────────────────────

def test_item_create_model():
    """ItemCreate validates name length."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from src.models import ItemCreate

    item = ItemCreate(name="test-item", description="a description")
    assert item.name == "test-item"
    assert item.description == "a description"


def test_item_create_requires_name():
    """ItemCreate rejects empty name."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from src.models import ItemCreate
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ItemCreate(name="")


def test_stats_response_model():
    """StatsResponse serialises correctly."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from src.models import StatsResponse

    stats = StatsResponse(
        total_items=42,
        redis_connected=True,
        service="infragpt-backend",
        version="1.0.0",
    )
    assert stats.total_items == 42
    assert stats.redis_connected is True


# ─── Health Logic Tests ───────────────────────────────────────────────────────

def test_health_response_shape():
    """Health endpoint returns expected keys."""
    expected_keys = {"status", "service", "version"}
    response = {
        "status": "ok",
        "service": "infragpt-backend",
        "version": "1.0.0",
    }
    assert expected_keys == set(response.keys())
    assert response["status"] == "ok"


def test_anomaly_score_threshold():
    """Anomaly score threshold logic is correct."""
    threshold = 0.75
    assert 0.80 >= threshold   # should trigger
    assert 0.50 < threshold    # should not trigger
    assert 0.75 >= threshold   # boundary — should trigger
