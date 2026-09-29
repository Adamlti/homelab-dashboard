import pytest
import socket


def pytest_sessionstart(session):
    # TestClient uses a portal thread and asyncio's socketpair wakeup.
    # Some sandboxes permit socketpair creation but deny send(), silently
    # losing the wakeup and leaving the very first request blocked forever.
    try:
        reader, writer = socket.socketpair()
        try:
            reader.settimeout(1)
            writer.sendall(b'w')
            if reader.recv(1) != b'w':
                raise OSError('Socketpair wakeup failed')
        finally:
            reader.close()
            writer.close()
    except OSError as exc:
        pytest.exit(
            f'Test environment blocks local socketpair wakeups ({exc}). '
            'Run the full backend suite in a native Ubuntu terminal or an approved '
            'environment permitting local IPC. Tests were NOT run.',
            returncode=4,
        )


@pytest.fixture(autouse=True)
def isolate_task_storage(tmp_path, monkeypatch):
    monkeypatch.setenv('DASHBOARD_TASKS_PATH', str(tmp_path / 'tasks.sqlite3'))
    monkeypatch.setenv('DASHBOARD_PUBLISHER_LOCK', str(tmp_path / 'publisher.lock'))
    monkeypatch.setenv('DASHBOARD_HISTORY_PATH', str(tmp_path / 'history.json'))
    monkeypatch.setenv('DASHBOARD_BACKUP_STATUS_PATH', str(tmp_path / 'latest-backup.json'))


@pytest.fixture
def eventually_get():
    """Monitoring responses refresh in the background; project writes are immediate."""
    import time

    def get(client, path, status):
        deadline = time.monotonic() + 2
        while True:
            response = client.get(path)
            if response.status_code == status or time.monotonic() >= deadline:
                assert response.status_code == status
                return response
            time.sleep(0.05)
    return get
