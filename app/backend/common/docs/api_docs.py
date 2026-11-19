"""Serve the shared Swagger viewer from common/static."""
from pathlib import Path
from flask import Blueprint

_static = Path(__file__).resolve().parents[1] / 'static'
api_docs = Blueprint('api_docs', __name__, static_folder=str(_static), static_url_path='/docs')


def init_api_docs(app):
    app.register_blueprint(api_docs)
