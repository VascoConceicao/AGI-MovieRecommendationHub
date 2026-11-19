"""Flask application entry point for the user service."""
import os
import click
from flask import Flask
from api.health import health
from api.discovery import users
from api.recommendation_context import agent_context
from api.auth import auth
from api.admin import admin
from api.profile import profile, internal
from services import accounts
from g15_common.monitoring.metrics import init_metrics
from g15_common.docs.api_docs import init_api_docs


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_URL"] = os.environ.get("DATABASE_URL", "")
    app.config['AUTH_COOKIE_SECURE'] = os.environ.get('AUTH_COOKIE_SECURE', 'true').lower() == 'true'
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
    app.config['AUTH_RESET_ENABLED'] = os.environ.get('AUTH_RESET_ENABLED', 'false').lower() == 'true'
    app.config['AUTH_RESET_TOKEN'] = os.environ.get('AUTH_RESET_TOKEN', '')
    app.register_blueprint(health)
    app.register_blueprint(agent_context)
    app.config['AGENT_CONTEXT_TOKEN'] = os.environ.get('AGENT_CONTEXT_TOKEN', '')
    app.register_blueprint(auth)
    app.register_blueprint(admin)
    app.register_blueprint(profile)
    app.register_blueprint(users)
    app.register_blueprint(internal)
    app.config['MOVIE_SERVICE_URL'] = os.environ.get('MOVIE_SERVICE_URL', 'http://127.0.0.1:4206')
    app.config['WATCHED_CLEANUP_TOKEN'] = os.environ.get('WATCHED_CLEANUP_TOKEN', '')
    app.config['RECOMMENDATION_SERVICE_URL'] = os.environ.get('RECOMMENDATION_SERVICE_URL', 'http://127.0.0.1:4207')
    app.config['RECOMMENDATION_API_TOKEN'] = os.environ.get('RECOMMENDATION_API_TOKEN', '')

    @app.cli.command('init-db')
    def init_db():
        """Create the initial account tables without deleting existing data."""
        accounts.initialize(app.config['DATABASE_URL'])
        click.echo('User account tables are ready.')

    @app.cli.command('clean-sessions')
    def clean_sessions():
        """Remove expired sessions; schedule periodically in deployment."""
        count = accounts.clean_sessions(app.config['DATABASE_URL'])
        click.echo(f'Removed {count} expired sessions.')

    init_metrics(app, "user-service")
    init_api_docs(app)
    return app
