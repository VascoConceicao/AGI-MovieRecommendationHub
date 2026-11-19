"""Prometheus instrumentation shared by the g15 backend services.

One in-process registry per container: images run a single gunicorn
worker (see Dockerfiles), so counters never split across processes.
"""
from time import perf_counter

from flask import Blueprint, Response, g, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REQUESTS = Counter(
    "g15_http_requests_total",
    "HTTP requests served.",
    ["service", "method", "route", "status"],
)
LATENCY = Histogram(
    "g15_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["service", "method", "route"],
)
DB_UP = Gauge(
    "g15_db_up",
    "Database reachability (1 = up, 0 = down).",
    ["service"],
)

metrics = Blueprint("metrics", __name__)


@metrics.get("/metrics")
def expose_metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


def init_metrics(app, service_name: str) -> None:
    """Register /metrics and per-request observation on a Flask app."""
    DB_UP.labels(service=service_name).set(0)
    app.register_blueprint(metrics)

    @app.before_request
    def _start_timer():
        g.started = perf_counter()

    @app.after_request
    def _observe(response):
        rule = request.url_rule.rule if request.url_rule else "unknown"
        REQUESTS.labels(
            service=service_name,
            method=request.method,
            route=rule,
            status=str(response.status_code),
        ).inc()
        LATENCY.labels(
            service=service_name,
            method=request.method,
            route=rule,
        ).observe(perf_counter() - g.get("started", perf_counter()))
        return response
