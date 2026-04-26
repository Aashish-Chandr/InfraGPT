"""
InfraGPT Backend Service — FastAPI application with full observability.
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    REGISTRY,
)
from pythonjsonlogger import jsonlogger
from sqlalchemy import text

from .models import Item, ItemCreate, StatsResponse
from .database import get_db, init_db

# ─── Logging ──────────────────────────────────────────────────────────────────

logger = logging.getLogger("infragpt.backend")
handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ─── OpenTelemetry Setup ──────────────────────────────────────────────────────

def setup_tracing() -> None:
    """Configure OpenTelemetry tracing with OTLP exporter."""
    resource = Resource.create(
        {
            "service.name": "infragpt-backend",
            "service.version": os.getenv("APP_VERSION", "1.0.0"),
            "deployment.environment": os.getenv("ENVIRONMENT", "production"),
        }
    )
    provider = TracerProvider(resource=resource)
    otlp_endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger-collector:4318/v1/traces"
    )
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


# ─── Prometheus Metrics ───────────────────────────────────────────────────────

REQUEST_COUNT = Counter(
    "backend_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "backend_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0],
)
ACTIVE_REQUESTS = Gauge(
    "backend_active_requests",
    "Number of active HTTP requests",
)
ITEMS_TOTAL = Gauge(
    "backend_items_total",
    "Total number of items in the database",
)
REDIS_OPERATIONS = Counter(
    "backend_redis_operations_total",
    "Total Redis operations",
    ["operation", "status"],
)

# ─── App Lifecycle ────────────────────────────────────────────────────────────

redis_client: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    global redis_client

    # Startup
    logger.info("Starting InfraGPT backend service")
    setup_tracing()

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    try:
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        await redis_client.ping()
        logger.info("Redis connection established", extra={"redis_url": redis_url})
    except Exception as exc:
        logger.warning("Redis unavailable, continuing without cache", extra={"error": str(exc)})
        redis_client = None

    await init_db()
    logger.info("Database initialized")

    yield

    # Shutdown
    logger.info("Shutting down InfraGPT backend service")
    if redis_client:
        await redis_client.close()


# ─── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="InfraGPT Backend",
    description="Backend service for the InfraGPT AI-powered Kubernetes platform",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auto-instrument FastAPI with OpenTelemetry
FastAPIInstrumentor.instrument_app(app)

# ─── Middleware ───────────────────────────────────────────────────────────────


@app.middleware("http")
async def metrics_middleware(request: Request, call_next: Any) -> Response:
    """Collect Prometheus metrics for every request."""
    ACTIVE_REQUESTS.inc()
    start_time = time.time()
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code,
        ).inc()
        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=request.url.path,
        ).observe(duration)
        return response
    finally:
        ACTIVE_REQUESTS.dec()


# ─── Routes ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def health_check() -> dict:
    """Kubernetes liveness probe endpoint."""
    return {
        "status": "ok",
        "service": "infragpt-backend",
        "version": os.getenv("APP_VERSION", "1.0.0"),
    }


@app.get("/ready")
async def readiness_check() -> dict:
    """Kubernetes readiness probe endpoint."""
    checks: dict[str, str] = {}

    # Check Redis
    if redis_client:
        try:
            await redis_client.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "unavailable"
    else:
        checks["redis"] = "not_configured"

    # Check DB
    try:
        async for db in get_db():
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    all_ok = all(v in ("ok", "not_configured") for v in checks.values())
    if not all_ok:
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "checks": checks},
        )
    return {"status": "ready", "checks": checks}


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/items", response_model=list[Item])
async def list_items() -> list[Item]:
    """List all items, with Redis caching."""
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("list_items"):
        # Try cache first
        if redis_client:
            try:
                cached = await redis_client.get("items:all")
                if cached:
                    REDIS_OPERATIONS.labels(operation="get", status="hit").inc()
                    import json
                    return json.loads(cached)
                REDIS_OPERATIONS.labels(operation="get", status="miss").inc()
            except Exception as exc:
                logger.warning("Redis get failed", extra={"error": str(exc)})

        # Fetch from DB
        async for db in get_db():
            sql = text(
                "SELECT id, name, description, created_at"
                " FROM items ORDER BY created_at DESC LIMIT 100"
            )
            result = await db.execute(sql)
            rows = result.fetchall()
            items = [
                Item(id=r[0], name=r[1], description=r[2], created_at=str(r[3]))
                for r in rows
            ]

        ITEMS_TOTAL.set(len(items))

        # Cache for 30 seconds
        if redis_client:
            try:
                import json
                payload = json.dumps([i.model_dump() for i in items])
                await redis_client.setex("items:all", 30, payload)
                REDIS_OPERATIONS.labels(operation="set", status="ok").inc()
            except Exception as exc:
                logger.warning("Redis set failed", extra={"error": str(exc)})

        return items


@app.post("/items", response_model=Item, status_code=201)
async def create_item(item: ItemCreate) -> Item:
    """Create a new item."""
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("create_item"):
        async for db in get_db():
            insert_sql = text(
                "INSERT INTO items (name, description)"
                " VALUES (:name, :description)"
                " RETURNING id, name, description, created_at"
            )
            result = await db.execute(
                insert_sql,
                {"name": item.name, "description": item.description},
            )
            await db.commit()
            row = result.fetchone()
            created = Item(id=row[0], name=row[1], description=row[2], created_at=str(row[3]))

        # Invalidate cache
        if redis_client:
            try:
                await redis_client.delete("items:all")
            except Exception:
                pass

        logger.info("Item created", extra={"item_id": created.id, "name": created.name})
        return created


@app.get("/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    """Return application statistics."""
    async for db in get_db():
        result = await db.execute(text("SELECT COUNT(*) FROM items"))
        count = result.scalar()

    redis_connected = False
    if redis_client:
        try:
            await redis_client.ping()
            redis_connected = True
        except Exception:
            pass

    return StatsResponse(
        total_items=count or 0,
        redis_connected=redis_connected,
        service="infragpt-backend",
        version=os.getenv("APP_VERSION", "1.0.0"),
    )


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True,
    )
