"""Flask application entry point for the recommendation service."""
import logging
import os
import click
from flask import Flask
from api.health import health
from api.context import context
from api.recommendations import recommendations
from api.generation import generation_api
from services import agent, generation
from services.recommendations import initialize
from g15_common.monitoring.metrics import init_metrics
from g15_common.docs.api_docs import init_api_docs


def configure_logging():
    """Make INFO lifecycle logs (generation jobs, pipeline summaries) visible: Flask and gunicorn install no root
    handler, so INFO records would otherwise be dropped. Does nothing when a handler already exists."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
                            format='%(asctime)s %(levelname)s %(name)s: %(message)s')


def create_app() -> Flask:
    configure_logging()
    app = Flask(__name__)
    app.config["DATABASE_URL"] = os.environ.get("DATABASE_URL", "")
    app.config['MOVIE_SERVICE_URL'] = os.environ.get('MOVIE_SERVICE_URL', 'http://127.0.0.1:4206')
    app.config['RECOMMENDATION_API_TOKEN'] = os.environ.get('RECOMMENDATION_API_TOKEN', '')
    app.config['RECOMMENDATION_RESET_TOKEN'] = os.environ.get('RECOMMENDATION_RESET_TOKEN', '')
    app.config['RECOMMENDATION_RESET_ENABLED'] = os.environ.get('RECOMMENDATION_RESET_ENABLED', 'false').lower() == 'true'
    app.config['USER_SERVICE_URL'] = os.environ.get('USER_SERVICE_URL', 'http://127.0.0.1:4208')
    app.config['AGENT_CONTEXT_TOKEN'] = os.environ.get('AGENT_CONTEXT_TOKEN', '')
    app.config['INFERENCE_SERVICE_URL'] = os.environ.get('INFERENCE_SERVICE_URL', 'http://127.0.0.1:4210')
    app.config['INFERENCE_TIMEOUT_SECONDS'] = int(os.environ.get('INFERENCE_TIMEOUT_SECONDS', '120'))             # first call; CPU inference needs more
    app.config['INFERENCE_RETRY_TIMEOUT_SECONDS'] = int(os.environ.get('INFERENCE_RETRY_TIMEOUT_SECONDS', '60'))
    app.config['INFERENCE_SYNOPSIS_CHARS'] = int(os.environ.get('INFERENCE_SYNOPSIS_CHARS', '200'))               # 0 = no synopsis in the prompt
    app.config['AUTO_INFERENCE_ENABLED'] = os.environ.get('AUTO_INFERENCE_ENABLED', 'true').lower() == 'true'      # false: agent jobs skip the LLM
    app.config['GENERATION_WORKER'] = os.environ.get('GENERATION_WORKER', 'true').lower() == 'true'
    app.config['GENERATION_MAX_RUNNING'] = int(os.environ.get('GENERATION_MAX_RUNNING', '1'))     # matches llama.cpp --parallel 1
    app.config['GENERATION_MAX_QUEUED'] = int(os.environ.get('GENERATION_MAX_QUEUED', '5'))
    app.config['AGENT_REFRESH_HOURS'] = float(os.environ.get('AGENT_REFRESH_HOURS', '24'))
    app.config['AGENT_RETRY_COOLDOWN_MINUTES'] = float(os.environ.get('AGENT_RETRY_COOLDOWN_MINUTES', '60'))
    app.config['AGENT_MAX_QUEUED'] = int(os.environ.get('AGENT_MAX_QUEUED', '2'))
    app.config['MAX_CONTENT_LENGTH'] = 32 * 1024
    app.register_blueprint(recommendations)
    app.register_blueprint(health)
    app.register_blueprint(context)
    app.register_blueprint(generation_api)

    @app.before_request
    def start_generation_worker():
        generation.ensure_started(app)        # serving processes only: CLI commands never run jobs. Returns nothing.

    @app.cli.command('init-db')
    def init_db():
        initialize(app.config['DATABASE_URL'])
        click.echo('Recommendation tables are ready.')

    @app.cli.command('agent-scan')
    def agent_scan():
        """One scan of the proactive agent: queue automatic generations for users that need them."""
        summary = agent.scan(app.config)
        click.echo('Agent scan ' + ('skipped: another scan is running.' if summary.skipped_scan else summary.describe() + '.'))
        if summary.discovery_failed:
            raise SystemExit(1)

    init_metrics(app, "recommendation-service")
    init_api_docs(app)
    return app
