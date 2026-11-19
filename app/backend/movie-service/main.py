"""Flask application entry point for the movie service."""
import os
from pathlib import Path
import click
from flask import Flask
from api.health import health
from api.catalog import movies
from services import catalog
from g15_common.monitoring.metrics import init_metrics
from g15_common.docs.api_docs import init_api_docs


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_URL"] = os.environ.get("DATABASE_URL", "")
    app.register_blueprint(health)
    app.register_blueprint(movies)
    app.config['MAX_CONTENT_LENGTH'] = 128 * 1024
    for key in ('MOVIE_WRITE_TOKEN', 'MOVIE_RESET_TOKEN', 'WATCHED_CLEANUP_TOKEN'):
        app.config[key] = os.environ.get(key, '')
    app.config['MOVIE_RESET_ENABLED'] = os.environ.get('MOVIE_RESET_ENABLED', 'false').lower() == 'true'
    app.config['USER_SERVICE_URL'] = os.environ.get('USER_SERVICE_URL', 'http://127.0.0.1:4208')
    app.config['MOVIE_MEDIA_DIR'] = str(Path(os.environ.get('MOVIE_MEDIA_DIR', str(Path(__file__).parent / 'assets/posters'))).resolve())

    @app.cli.command('init-db')
    def init_db():
        catalog.initialize(app.config['DATABASE_URL'])
        click.echo('Movie catalog tables are ready.')

    init_metrics(app, "movie-service")
    init_api_docs(app)
    return app
