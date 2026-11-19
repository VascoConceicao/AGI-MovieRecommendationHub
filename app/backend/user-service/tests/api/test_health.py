import pytest
from main import create_app
from api import health


@pytest.mark.parametrize('ready,status', [(True, 200), (False, 503)])
def test_health_reports_database_state(monkeypatch, ready, status):
    monkeypatch.setattr(health, 'database_is_ready', lambda url: ready)
    response = create_app().test_client().get('/health')
    assert response.status_code == status
    assert response.json['database'] == ('up' if ready else 'down')
    assert response.headers['Cache-Control'] == 'no-store'
