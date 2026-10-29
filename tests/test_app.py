import importlib
import os
import sys
import tempfile
import time

import pytest
from fastapi.testclient import TestClient
from gpiozero.pins.mock import MockFactory, MockPWMPin

os.environ.setdefault("DAYANPI_USER", "tester")
os.environ.setdefault("DAYANPI_PASSWORD", "secret")
os.environ.setdefault("DAYANPI_DATA_DIR", tempfile.mkdtemp(prefix="dayanpi-test-"))

import app  # noqa: E402  (auth env must be set before import)
import camera  # noqa: E402
import collector  # noqa: E402
import drivetrain  # noqa: E402
import focus_worker  # noqa: E402

AUTH = (app.AUTH_USER, app.AUTH_PASSWORD)
FORWARD = {"left": 1, "right": 1}


@pytest.fixture(autouse=True)
def mac_friendly(monkeypatch):
    # No /proc, vcgencmd or /dev/video0 on the Mac, and no model loading per test.
    monkeypatch.setattr(app.sampler, "sample", lambda: None)
    monkeypatch.setattr(collector, "snapshot", lambda sampler: {"fake": True})
    monkeypatch.setattr(camera, "RECONNECT_SLEEP_S", 0.01)
    monkeypatch.setattr(focus_worker, "build_scanner", lambda: None)


@pytest.fixture
def factory(monkeypatch):
    mock_factory = MockFactory(pin_class=MockPWMPin)
    monkeypatch.setattr(app, "DriveTrain", lambda: drivetrain.DriveTrain(pin_factory=mock_factory))
    yield mock_factory
    mock_factory.close()


def read_enable(factory):
    enable_duty = factory.pin(drivetrain.LEFT_ENABLE_PIN).state
    return enable_duty


def test_dashboard_runs_without_motors(monkeypatch, caplog):
    # Same failure as a venv that can't see apt's gpiozero.
    monkeypatch.setitem(sys.modules, "gpiozero", None)
    with TestClient(app.app) as client:
        assert client.get("/api/health", auth=AUTH).status_code == 200
        response = client.post("/api/drive", json=FORWARD, auth=AUTH)
        assert response.status_code == 503
        assert response.json()["detail"] == "Motors unavailable"
    assert "motors unavailable" in caplog.text


def test_drivetrain_imports_without_gpiozero(monkeypatch):
    monkeypatch.setitem(sys.modules, "gpiozero", None)
    monkeypatch.delitem(sys.modules, "drivetrain")
    fresh_drivetrain = importlib.import_module("drivetrain")
    with pytest.raises(ImportError):
        fresh_drivetrain.DriveTrain()


def test_dashboard_runs_without_camera(factory, caplog):
    with TestClient(app.app) as client:
        assert client.get("/api/health", auth=AUTH).status_code == 200
        assert app.stream._thread.is_alive()
    assert "camera unavailable at startup" in caplog.text


def test_drive_moves_then_watchdog_stops(factory):
    with TestClient(app.app) as client:
        response = client.post("/api/drive", json=FORWARD, auth=AUTH)
        assert response.status_code == 200
        assert read_enable(factory) == pytest.approx(drivetrain.MAX_SPEED)
        time.sleep(app.DRIVE_TIMEOUT_S + 3 * app.WATCHDOG_INTERVAL_S)
        assert read_enable(factory) == 0


def test_drive_needs_auth(factory):
    with TestClient(app.app) as client:
        response = client.post("/api/drive", json=FORWARD)
        assert response.status_code == 401
        assert read_enable(factory) == 0


def test_drive_rejects_out_of_range(factory):
    with TestClient(app.app) as client:
        response = client.post("/api/drive", json={"left": 2, "right": 0}, auth=AUTH)
        assert response.status_code == 422
        assert read_enable(factory) == 0


def test_shutdown_stops_motors(factory):
    with TestClient(app.app) as client:
        client.post("/api/drive", json=FORWARD, auth=AUTH)
        assert read_enable(factory) > 0
    assert read_enable(factory) == 0


def test_focus_api_reports_disabled_without_models(factory):
    with TestClient(app.app) as client:
        response = client.get("/api/focus", auth=AUTH)
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["state"] == "unknown"
        assert isinstance(body["segments"], list)
        assert client.get("/api/focus").status_code == 401


def test_stats_snapshot_carries_focus(factory):
    with TestClient(app.app) as client:
        deadline = time.monotonic() + 3
        body = {}
        while "focus" not in body and time.monotonic() < deadline:
            body = client.get("/api/stats", auth=AUTH).json()
            time.sleep(0.05)
        assert body["fake"] is True
        assert body["focus"]["state"] == "unknown"
        assert "today" in body["focus"]


def test_mac_app_route_records_the_front_app(factory):
    with TestClient(app.app) as client:
        assert client.post("/api/mac/app", json={"app": "Code"}).status_code == 401
        first = client.post("/api/mac/app", json={"app": "  Code "}, auth=AUTH)
        assert first.status_code == 200
        assert first.json()["changed"] is True
        again = client.post("/api/mac/app", json={"app": "Code"}, auth=AUTH)
        assert again.json()["changed"] is False
        assert client.get("/api/focus", auth=AUTH).json()["app"] == "Code"
        assert client.post("/api/mac/app", json={"app": ""}, auth=AUTH).status_code == 422
        assert client.post("/api/mac/app", json={"app": "x" * 101}, auth=AUTH).status_code == 422


def test_block_route_starts_stops_and_toggles(factory):
    with TestClient(app.app) as client:
        assert client.post("/api/focus/block", json={"action": "stop"}, auth=AUTH).json()["active"] is False
        started = client.post("/api/focus/block", json={"action": "start"}, auth=AUTH).json()
        assert started == {"status": "ok", "active": True, "changed": True}
        assert client.get("/api/focus", auth=AUTH).json()["block"]["active"] is True
        toggled = client.post("/api/focus/block", json={"action": "toggle"}, auth=AUTH).json()
        assert toggled["active"] is False
        assert client.post("/api/focus/block", json={"action": "dance"}, auth=AUTH).status_code == 422


def test_worker_runs_when_a_scanner_exists(factory, monkeypatch):
    class FakeScanner:
        def scan(self, image):
            raise AssertionError("no frames here, so scan must not be called")

    monkeypatch.setattr(focus_worker, "build_scanner", lambda: FakeScanner())
    with TestClient(app.app) as client:
        assert app.worker is not None
        assert app.worker.running
        assert client.get("/api/focus", auth=AUTH).json()["enabled"] is True
    assert app.worker is None
