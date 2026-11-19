"""Database readiness; no product endpoints are exposed yet."""
from flask import Blueprint, current_app, jsonify
from g15_common.monitoring.metrics import DB_UP
from services.database import database_is_ready

health = Blueprint("health", __name__)


@health.get("/health")
def check_health():
    ready = database_is_ready(current_app.config["DATABASE_URL"])
    DB_UP.labels(service="recommendation-service").set(1 if ready else 0)
    response = jsonify(
        service="recommendation-service",
        status="ok" if ready else "unavailable",
        database="up" if ready else "down",
    )
    response.headers["Cache-Control"] = "no-store"
    return response, 200 if ready else 503
