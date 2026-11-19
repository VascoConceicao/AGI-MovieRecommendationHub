"""Only this service's PostgreSQL instance is checked."""
from pathlib import Path
import psycopg
from g15_common.db.query_loader import load_query

_QUERY = load_query(Path(__file__).resolve().parents[1] / "db" / "sql", "health.sql")


def database_is_ready(database_url: str) -> bool:
    if not database_url:
        return False
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=3,
            options="-c statement_timeout=2000",
            autocommit=True,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(_QUERY)
                return cursor.fetchone() == (1,)
    except psycopg.Error:
        # Never return connection details, credentials, or raw driver errors.
        return False
