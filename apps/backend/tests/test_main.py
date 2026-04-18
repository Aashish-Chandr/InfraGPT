"""Tests for the backend service."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    mock.get = AsyncMock(return_value=None)
    mock.setex = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=1)
    return mock


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = []
    result.fetchone.return_value = (1, "test", "desc", "2024-01-01")
    result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_health_endpoint():
    """Test the health check endpoint."""
    with patch("src.main.setup_tracing"), \
         patch("src.main.init_db", new_callable=AsyncMock), \
         patch("aioredis.from_url"):
        from src.main import app
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "infragpt-backend"


@pytest.mark.asyncio
async def test_metrics_endpoint():
    """Test the Prometheus metrics endpoint."""
    with patch("src.main.setup_tracing"), \
         patch("src.main.init_db", new_callable=AsyncMock), \
         patch("aioredis.from_url"):
        from src.main import app
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/metrics")
        assert response.status_code == 200
        assert "backend_http_requests_total" in response.text
