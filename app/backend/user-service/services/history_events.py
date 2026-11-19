"""Committed PostgreSQL changes streamed to the owning user's browser."""
from threading import BoundedSemaphore
import psycopg
from services import accounts

# Reserve normal request capacity in the 32-thread production worker.
_SLOTS = BoundedSemaphore(16)


class StreamBusy(Exception):
    pass


def subscribe(database_url, user_id, token):
    if not _SLOTS.acquire(blocking=False):
        raise StreamBusy()
    try:
        connection = psycopg.connect(database_url, autocommit=True, connect_timeout=3,
                                     options='-c statement_timeout=5000')
        try:
            connection.execute('LISTEN watched_history')
        except BaseException:
            connection.close()
            raise
    except BaseException:
        _SLOTS.release()
        raise
    closed = False

    def close():
        nonlocal closed
        if not closed:
            closed = True
            connection.close()
            _SLOTS.release()

    def events():
        try:
            # Listener is active before the browser refreshes, covering reconnect gaps.
            yield 'retry: 3000\nevent: ready\ndata: {}\n\n'
            while True:
                changed = False
                for notification in connection.notifies(timeout=20, stop_after=1):
                    changed = notification.payload in (user_id, 'all')
                # Revalidate revoked/expired sessions; this is not history polling.
                user = accounts.current_user(database_url, token)
                if not user or user['id'] != user_id:
                    yield 'event: signed-out\ndata: {}\n\n'
                    return
                if changed:
                    yield 'event: watched-changed\ndata: {}\n\n'
                else:
                    yield ': keep-alive\n\n'
        except psycopg.Error:
            # Closing causes EventSource to reconnect and resync through ready.
            return
        finally:
            close()

    return events(), close
