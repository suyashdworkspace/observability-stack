"""
FastAPI Application with full observability instrumentation:
- Prometheus metrics (prometheus_client)
- Structured JSON logging
- OpenTelemetry distributed tracing
"""

import logging
import json
import time
import random
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
import uvicorn
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
import os

# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURED JSON LOGGER
# ─────────────────────────────────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": "fastapi-demo-app",
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id
        if hasattr(record, "span_id"):
            log_data["span_id"] = record.span_id
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


logger = get_logger("fastapi-app")

# ─────────────────────────────────────────────────────────────────────────────
# OPENTELEMETRY SETUP
# ─────────────────────────────────────────────────────────────────────────────

OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "fastapi-demo-app")

resource = Resource.create({"service.name": SERVICE_NAME, "service.version": "1.0.0"})
tracer_provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)
span_processor = BatchSpanProcessor(otlp_exporter)
tracer_provider.add_span_processor(span_processor)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# PROMETHEUS METRICS
# ─────────────────────────────────────────────────────────────────────────────

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

ACTIVE_REQUESTS = Gauge(
    "http_active_requests",
    "Number of active HTTP requests"
)

ITEMS_PROCESSED = Counter(
    "items_processed_total",
    "Total items processed",
    ["status"]
)

BUSINESS_ERRORS = Counter(
    "business_errors_total",
    "Total business logic errors",
    ["error_type"]
)

APP_INFO = Gauge(
    "app_info",
    "Application information",
    ["version", "environment"]
)

# ─────────────────────────────────────────────────────────────────────────────
# APPLICATION LIFECYCLE
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    APP_INFO.labels(version="1.0.0", environment=os.getenv("APP_ENV", "development")).set(1)
    logger.info("FastAPI observability demo application started", extra={"trace_id": "startup"})
    yield
    # Shutdown
    logger.info("FastAPI application shutting down")
    tracer_provider.shutdown()


app = FastAPI(
    title="Observability Demo API",
    description="FastAPI app with Prometheus, Loki, and Jaeger instrumentation",
    version="1.0.0",
    lifespan=lifespan
)

# Instrument FastAPI with OpenTelemetry
FastAPIInstrumentor.instrument_app(app)

# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE — Request Tracking
# ─────────────────────────────────────────────────────────────────────────────

@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    ACTIVE_REQUESTS.inc()
    start_time = time.time()
    request_id = str(uuid.uuid4())

    # Get current trace context
    current_span = trace.get_current_span()
    trace_id = format(current_span.get_span_context().trace_id, "032x") if current_span else "no-trace"
    span_id = format(current_span.get_span_context().span_id, "016x") if current_span else "no-span"

    try:
        response = await call_next(request)
        duration = time.time() - start_time

        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status=str(response.status_code)
        ).inc()

        REQUEST_DURATION.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(duration)

        logger.info(
            f"{request.method} {request.url.path} {response.status_code} {duration:.4f}s",
            extra={
                "trace_id": trace_id,
                "span_id": span_id,
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2)
            }
        )
        return response

    except Exception as exc:
        duration = time.time() - start_time
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status="500"
        ).inc()
        logger.error(
            f"Unhandled exception on {request.method} {request.url.path}: {exc}",
            exc_info=True,
            extra={"trace_id": trace_id, "span_id": span_id}
        )
        raise
    finally:
        ACTIVE_REQUESTS.dec()

# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": SERVICE_NAME, "version": "1.0.0"}


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/items")
async def get_items():
    with tracer.start_as_current_span("get-items") as span:
        span.set_attribute("db.system", "simulated")
        span.set_attribute("db.operation", "SELECT")

        # Simulate DB query latency
        time.sleep(random.uniform(0.01, 0.1))

        items = [
            {"id": i, "name": f"Item {i}", "value": random.randint(1, 100)}
            for i in range(1, random.randint(5, 20))
        ]

        ITEMS_PROCESSED.labels(status="success").inc(len(items))
        span.set_attribute("items.count", len(items))
        logger.info(f"Retrieved {len(items)} items")
        return {"items": items, "count": len(items)}


@app.get("/api/items/{item_id}")
async def get_item(item_id: int):
    with tracer.start_as_current_span("get-item-by-id") as span:
        span.set_attribute("item.id", item_id)

        if item_id <= 0:
            BUSINESS_ERRORS.labels(error_type="invalid_id").inc()
            span.set_attribute("error", True)
            raise HTTPException(status_code=400, detail="Invalid item ID")

        if item_id > 1000:
            BUSINESS_ERRORS.labels(error_type="not_found").inc()
            span.set_attribute("error", True)
            raise HTTPException(status_code=404, detail=f"Item {item_id} not found")

        time.sleep(random.uniform(0.005, 0.05))
        return {"id": item_id, "name": f"Item {item_id}", "value": random.randint(1, 100)}


@app.get("/api/slow")
async def slow_endpoint():
    with tracer.start_as_current_span("slow-operation") as span:
        delay = random.uniform(1.0, 3.0)
        span.set_attribute("simulated.delay_seconds", delay)
        logger.warning(f"Slow endpoint called, sleeping for {delay:.2f}s")
        time.sleep(delay)
        return {"message": "Slow response completed", "delay_seconds": round(delay, 2)}


@app.get("/api/error-simulation")
async def error_simulation():
    with tracer.start_as_current_span("error-simulation") as span:
        error_type = random.choice(["timeout", "db_error", "external_api_failure"])
        span.set_attribute("error", True)
        span.set_attribute("error.type", error_type)
        BUSINESS_ERRORS.labels(error_type=error_type).inc()
        logger.error(f"Simulated error occurred: {error_type}")
        raise HTTPException(status_code=500, detail=f"Simulated {error_type}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_config=None)
