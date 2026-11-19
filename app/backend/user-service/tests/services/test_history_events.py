from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest
from services import history_events as events


@pytest.fixture
def setup(monkeypatch):
    slots = Mock()
    slots.acquire.return_value = True
    conn = Mock()
    monkeypatch.setattr(events, '_SLOTS', slots)
    monkeypatch.setattr(events.psycopg, 'connect', Mock(return_value=conn))
    monkeypatch.setattr(events.accounts, 'current_user', Mock(return_value={'id': 'user'}))
    return slots, conn


def test_capacity_does_not_connect(setup):
    slots, conn = setup
    slots.acquire.return_value = False
    with pytest.raises(events.StreamBusy):
        events.subscribe('db', 'user', 'token')
    events.psycopg.connect.assert_not_called()
    slots.release.assert_not_called()


@pytest.mark.parametrize('stage', ['connect', 'listen'])
def test_setup_failure_releases_slot(setup, stage):
    slots, conn = setup
    target = events.psycopg.connect if stage == 'connect' else conn.execute
    target.side_effect = psycopg.OperationalError('offline')
    with pytest.raises(psycopg.Error):
        events.subscribe('db', 'user', 'token')
    slots.release.assert_called_once()
    assert conn.close.call_count == (stage == 'listen')


@pytest.mark.parametrize('payload,event', [('user', 'watched-changed'), ('all', 'watched-changed'), ('other', 'keep-alive'), (None, 'keep-alive')])
def test_stream_notifications_and_idempotent_close(setup, payload, event):
    slots, conn = setup
    conn.notifies.return_value = [] if payload is None else [SimpleNamespace(payload=payload)]
    stream, close = events.subscribe('db', 'user', 'token')
    conn.execute.assert_called_once_with('LISTEN watched_history')
    assert 'event: ready' in next(stream)
    assert event in next(stream)
    events.accounts.current_user.assert_called_once_with('db', 'token')
    stream.close()
    close()
    conn.close.assert_called_once()
    slots.release.assert_called_once()


@pytest.mark.parametrize('user', [None, {'id': 'other'}])
def test_revoked_session_closes_stream(setup, user):
    slots, conn = setup
    conn.notifies.return_value = []
    events.accounts.current_user.return_value = user
    stream, close = events.subscribe('db', 'user', 'token')
    next(stream)
    assert 'signed-out' in next(stream)
    with pytest.raises(StopIteration):
        next(stream)
    slots.release.assert_called_once()


def test_database_failure_ends_stream(setup):
    slots, conn = setup
    conn.notifies.side_effect = psycopg.OperationalError('offline')
    stream, close = events.subscribe('db', 'user', 'token')
    next(stream)
    with pytest.raises(StopIteration):
        next(stream)
    conn.close.assert_called_once()
    slots.release.assert_called_once()
