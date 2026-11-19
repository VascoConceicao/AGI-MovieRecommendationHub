from main import create_app


def test_init_db_command(monkeypatch):
    from unittest.mock import Mock
    initialize = Mock()
    monkeypatch.setattr('main.catalog.initialize', initialize)
    app = create_app()
    app.config['DATABASE_URL'] = 'test-only'
    result = app.test_cli_runner().invoke(args=['init-db'])
    assert result.exit_code == 0
    assert 'tables are ready' in result.output
    initialize.assert_called_once_with('test-only')


def test_metrics_and_shared_docs_are_served():
    client = create_app().test_client()
    assert client.get('/metrics').status_code == 200
    assert b'SwaggerUIBundle' in client.get('/docs/swagger.html').data
