from flask import Flask
from g15_common.monitoring.metrics import init_metrics


def test_metrics_observe_routes_and_missing_paths():
    app = Flask(__name__)
    init_metrics(app, 'common-test')
    app.add_url_rule('/hello', view_func=lambda: 'hello')
    client = app.test_client()
    assert client.get('/hello').status_code == 200
    assert client.get('/missing').status_code == 404
    response = client.get('/metrics')
    assert response.status_code == 200
    assert b'route="/hello"' in response.data
    assert b'route="unknown"' in response.data
