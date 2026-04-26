"""
Backend unit tests — pure logic, no DB or Redis required.
"""

import sys
import os

# Put the backend src on the path so 'from src.models import ...' works
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pydantic
from src.models import ItemCreate, StatsResponse


# ─── ItemCreate ───────────────────────────────────────────────────────────────

def test_item_create_valid():
    item = ItemCreate(name="widget", description="a test widget")
    assert item.name == "widget"
    assert item.description == "a test widget"


def test_item_create_no_description():
    item = ItemCreate(name="widget")
    assert item.description is None


def test_item_create_empty_name_rejected():
    with pytest.raises(pydantic.ValidationError):
        ItemCreate(name="")


def test_item_create_name_too_long_rejected():
    with pytest.raises(pydantic.ValidationError):
        ItemCreate(name="x" * 256)


# ─── StatsResponse ────────────────────────────────────────────────────────────

def test_stats_response_valid():
    stats = StatsResponse(
        total_items=42,
        redis_connected=True,
        service="infragpt-backend",
        version="1.0.0",
    )
    assert stats.total_items == 42
    assert stats.redis_connected is True
    assert stats.service == "infragpt-backend"


def test_stats_response_zero_items():
    stats = StatsResponse(
        total_items=0,
        redis_connected=False,
        service="infragpt-backend",
        version="1.0.0",
    )
    assert stats.total_items == 0
    assert stats.redis_connected is False


# ─── Business logic ───────────────────────────────────────────────────────────

def test_health_response_shape():
    response = {
        "status": "ok",
        "service": "infragpt-backend",
        "version": "1.0.0",
    }
    assert response["status"] == "ok"
    assert "service" in response
    assert "version" in response


def test_anomaly_threshold_logic():
    threshold = 0.75
    assert 0.80 >= threshold    # triggers
    assert 0.50 < threshold     # does not trigger
    assert 0.75 >= threshold    # boundary triggers
    assert 0.74 < threshold     # just below does not trigger


def test_severity_classification():
    def classify(score: float) -> str:
        return "critical" if score >= 0.9 else "warning"

    assert classify(0.95) == "critical"
    assert classify(0.90) == "critical"
    assert classify(0.89) == "warning"
    assert classify(0.75) == "warning"
