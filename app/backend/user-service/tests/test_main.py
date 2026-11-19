from main import create_app


def test_metrics_and_shared_docs_are_served():
    client = create_app().test_client()
    assert client.get('/metrics').status_code == 200
    assert b'SwaggerUIBundle' in client.get('/docs/swagger.html').data



from api import auth


def test_schema_and_cleanup_commands(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'test-only')
    app = create_app()
    calls = []
    monkeypatch.setattr(auth.accounts, 'initialize', lambda url: calls.append(url))
    monkeypatch.setattr(auth.accounts, 'clean_sessions', lambda url: 3)
    assert app.test_cli_runner().invoke(args=['init-db']).exit_code == 0
    assert calls == ['test-only']
    assert '3' in app.test_cli_runner().invoke(args=['clean-sessions']).output
