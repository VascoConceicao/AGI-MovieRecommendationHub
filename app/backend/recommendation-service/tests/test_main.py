from main import create_app


def test_init_db_command(monkeypatch):
    from unittest.mock import Mock
    initialize = Mock()
    monkeypatch.setattr('main.initialize', initialize)
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


def test_logging_is_configured_only_when_no_handler_exists(monkeypatch):
    import logging
    from unittest.mock import Mock
    import main
    root = logging.getLogger()
    basic = Mock()
    monkeypatch.setattr(logging, 'basicConfig', basic)
    monkeypatch.setattr(root, 'handlers', [])
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    main.configure_logging()
    assert basic.call_args.kwargs['level'] == 'INFO'
    monkeypatch.setenv('LOG_LEVEL', 'warning')
    main.configure_logging()
    assert basic.call_args.kwargs['level'] == 'WARNING'
    basic.reset_mock()
    monkeypatch.setattr(root, 'handlers', [logging.NullHandler()])
    main.configure_logging()
    basic.assert_not_called()


def test_agent_scan_command_runs_one_scan_with_the_app_config(monkeypatch):
    from unittest.mock import Mock
    from services import agent
    scan = Mock(return_value=agent.ScanSummary(users=4, scheduled=2, skipped_fresh=1, skipped_active=1))
    monkeypatch.setattr('main.agent.scan', scan)
    app = create_app()
    result = app.test_cli_runner().invoke(args=['agent-scan'])
    assert result.exit_code == 0 and result.output.strip() == 'Agent scan users=4 scheduled=2 fresh=1 cooldown=0 active=1 deferred=0 errors=0.'
    scan.assert_called_once_with(app.config)
    assert app.config['AGENT_REFRESH_HOURS'] == 24 and app.config['AGENT_RETRY_COOLDOWN_MINUTES'] == 60 and app.config['AGENT_MAX_QUEUED'] == 2


def test_agent_scan_command_reports_a_skipped_scan_and_fails_on_discovery_errors(monkeypatch):
    from unittest.mock import Mock
    from services import agent
    app = create_app()
    monkeypatch.setattr('main.agent.scan', Mock(return_value=agent.ScanSummary(skipped_scan=True)))
    skipped = app.test_cli_runner().invoke(args=['agent-scan'])
    assert skipped.exit_code == 0 and 'skipped' in skipped.output
    monkeypatch.setattr('main.agent.scan', Mock(return_value=agent.ScanSummary(discovery_failed=True, errors=1)))
    failed = app.test_cli_runner().invoke(args=['agent-scan'])
    assert failed.exit_code == 1 and 'errors=1' in failed.output


def test_agent_config_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv('AGENT_REFRESH_HOURS', '6')
    monkeypatch.setenv('AGENT_RETRY_COOLDOWN_MINUTES', '15')
    monkeypatch.setenv('AGENT_MAX_QUEUED', '3')
    app = create_app()
    assert (app.config['AGENT_REFRESH_HOURS'], app.config['AGENT_RETRY_COOLDOWN_MINUTES'], app.config['AGENT_MAX_QUEUED']) == (6.0, 15.0, 3)
