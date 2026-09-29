import importlib
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient
from gpiozero.pins.mock import MockFactory, MockPWMPin

os.environ.setdefault("DAYANPI_USER", "tester")
os.environ.setdefault("DAYANPI_PASSWORD", "secret")

import app  # noqa: E402  (auth env must be set before import)
import camera  # noqa: E402
import collector  # noqa: E402
import drivetrain  # noqa: E402

AUTH = (app.AUTH_USER, app.AUTH_PASSWORD)
FORWARD = {"left": 1, "right": 1}


@pytest.fixture(autouse=True)
def mac_friendly(monkeypatch):
    # No /proc, vcgencmd or /dev/video0 on the Mac.
    monkeypatch.setattr(app.sampler, "sample", lambda: None)
    monkeypatch.setattr(collector, "snapshot", lambda sampler: {"fake": True})
    monkeypatch.setattr(camera, "RECONNECT_SLEEP_S", 0.01)


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
