import importlib
import os
import re
import sys
import tempfile
import time

import pytest
from fastapi.testclient import TestClient
from gpiozero.pins.mock import MockFactory, MockPWMPin

os.environ.setdefault("DAYANPI_USER", "tester")
os.environ.setdefault("DAYANPI_PASSWORD", "secret")
os.environ.setdefault("DAYANPI_DATA_DIR", tempfile.mkdtemp(prefix="dayanpi-test-"))

from dayanpi import app  # noqa: E402  (auth env must be set before import)
from dayanpi.hardware import camera  # noqa: E402
from dayanpi.hardware import collector  # noqa: E402
from dayanpi.hardware import drivetrain  # noqa: E402
from dayanpi.focus import worker as focus_worker  # noqa: E402

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
    monkeypatch.delitem(sys.modules, "dayanpi.hardware.drivetrain")
    fresh_drivetrain = importlib.import_module("dayanpi.hardware.drivetrain")
    with pytest.raises(ImportError):
        fresh_drivetrain.DriveTrain()


def test_dashboard_runs_without_camera(factory, caplog):
    with TestClient(app.app) as client:
        assert client.get("/api/health", auth=AUTH).status_code == 200
        assert app.stream._thread.is_alive()
    assert "camera unavailable at startup" in caplog.text


def test_dashboard_serves_every_file_it_links(factory):
    with TestClient(app.app) as client:
        page = client.get("/", auth=AUTH)
        assert page.status_code == 200
        linked = re.findall(r'(?:src|href)="(/[^"#?]+)"', page.text)
        assert {"/styles.css", "/ui.js", "/app.js", "/focus.js"} <= set(linked)
        for path in linked:
            assert client.get(path, auth=AUTH).status_code == 200, path
        assert client.get("/", headers={}).status_code == 401


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


def test_voice_say_route_logs_when_the_voice_is_off(factory, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="dayanpi.hardware.voice")
    with TestClient(app.app) as client:
        assert client.post("/api/voice/say", json={"text": "Phone down."}).status_code == 401
        response = client.post("/api/voice/say", json={"text": "Phone down."}, auth=AUTH)
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "queued": False, "backend": "off"}
        assert client.post("/api/voice/say", json={"text": ""}, auth=AUTH).status_code == 422
        status = client.get("/api/focus", auth=AUTH).json()
        assert status["voice"] == {"enabled": False, "backend": "off", "problem": None}
    assert "would say: 'Phone down.'" in caplog.text


def test_callouts_reach_the_voice(monkeypatch):
    from dayanpi.focus import tracker as focus

    said = []
    monkeypatch.setattr(app.voice, "say", lambda text: said.append(text) or True)
    update = focus.FocusUpdate(
        state="phone",
        changed=True,
        previous_state="working",
        callouts=[focus.Callout("instant_pickup", "Already?"), focus.Callout("snack", "Snack 1.", speak=False)],
    )
    app.handle_focus_update(update, time.time())
    assert said == ["Already?"]


def test_gesture_toggles_the_block_and_speaks(monkeypatch, factory):
    said = []
    monkeypatch.setattr(app.voice, "say", lambda text: said.append(text) or True)
    with TestClient(app.app) as client:
        client.post("/api/focus/block", json={"action": "stop"}, auth=AUTH)
        app.handle_gesture("toggle_block", time.time())
        assert client.get("/api/focus", auth=AUTH).json()["block"]["active"] is True
        app.handle_gesture("toggle_block", time.time())
        assert client.get("/api/focus", auth=AUTH).json()["block"]["active"] is False
    assert said == ["Block started.", "Block stopped."]


def test_sign_preview_renders_and_rides_the_status(factory):
    with TestClient(app.app) as client:
        deadline = time.monotonic() + 3
        body = {}
        while not body.get("sign_png") and time.monotonic() < deadline:
            body = client.get("/api/focus", auth=AUTH).json()
            time.sleep(0.05)
        assert body["sign"]["mode"] == "preview"
        assert body["sign"]["page"] == "now"
        assert body["sign"]["version"] >= 1
        assert body["sign_png"], "the sign preview should be in the focus status"
        # The stats stream only carries the PNG when the picture changed since the last snapshot.
        stats = client.get("/api/stats", auth=AUTH).json()
        assert "sign" in stats["focus"]
        response = client.get("/api/sign.png", auth=AUTH)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert client.get("/api/sign.png").status_code == 401


def test_the_site_can_flip_the_sign_page(factory):
    with TestClient(app.app) as client:
        assert client.post("/api/sign/page", json={"step": 1}).status_code == 401
        assert client.post("/api/sign/page", json={"step": 1}, auth=AUTH).json() == {"status": "ok", "page": "today"}
        assert client.post("/api/sign/page", json={"step": 1}, auth=AUTH).json()["page"] == "summary"
        assert client.post("/api/sign/page", json={"step": -1}, auth=AUTH).json()["page"] == "today"
        assert client.post("/api/sign/page", json={"step": 2}, auth=AUTH).status_code == 422
        assert client.get("/api/focus", auth=AUTH).json()["sign"]["page"] == "today"


def test_flipping_an_off_sign_says_so(monkeypatch, factory):
    monkeypatch.setattr(app, "SIGN_MODE", "off")
    with TestClient(app.app) as client:
        response = client.post("/api/sign/page", json={"step": 1}, auth=AUTH)
        assert response.status_code == 503
        assert response.json()["detail"] == "Sign is off"


def test_focus_api_lists_todays_snack_times(factory):
    with TestClient(app.app) as client:
        assert client.get("/api/focus", auth=AUTH).json()["snack_times"] == []


def test_callouts_and_gestures_reach_the_sign(monkeypatch, factory):
    from dayanpi.focus import tracker as focus

    monkeypatch.setattr(app.voice, "say", lambda text: True)
    with TestClient(app.app):
        controller = app.sign_controller
        assert controller is not None
        app.handle_focus_update(
            focus.FocusUpdate(state="phone", changed=True, previous_state="working", callouts=[focus.Callout("snack", "Snack number 1.", speak=False)]),
            time.time(),
        )
        assert controller._queue or controller._active is not None
        app.handle_gesture("next_page", time.time())
        assert controller.page == "today"
        app.handle_gesture("previous_page", time.time())
        assert controller.page == "now"
    assert app.sign_controller is None


def test_panel_mode_keeps_the_motors_off(monkeypatch, factory, caplog):
    import logging
    from dayanpi.sign import renderer as sign

    caplog.set_level(logging.INFO, logger="dayanpi.app")
    monkeypatch.setattr(app, "SIGN_MODE", "panel")
    monkeypatch.setattr(sign, "PanelOutput", lambda: (_ for _ in ()).throw(ImportError("no piomatter")))
    monkeypatch.setattr(app, "PanelOutput", lambda: (_ for _ in ()).throw(ImportError("no piomatter")))
    with TestClient(app.app) as client:
        assert app.drive_train is None
        assert client.post("/api/drive", json=FORWARD, auth=AUTH).status_code == 503
        assert app.sign_controller is not None
    assert "panels unavailable, preview only" in caplog.text
    assert "motors stay off" in caplog.text


def test_worker_runs_when_a_scanner_exists(factory, monkeypatch):
    class FakeScanner:
        def scan(self, image):
            raise AssertionError("no frames here, so scan must not be called")

    monkeypatch.setattr(focus_worker, "build_scanner", lambda: FakeScanner())
    with TestClient(app.app) as client:
        assert app.worker is not None
        assert app.worker.running
        status = client.get("/api/focus", auth=AUTH).json()
        assert status["enabled"] is True
        assert status["overlay"] is None


def test_focus_status_carries_the_boxes_and_their_age(factory, monkeypatch):
    from dayanpi.focus.overlay import Overlay, OverlayBox

    class FakeScanner:
        def scan(self, image):
            raise AssertionError("no frames here")

    monkeypatch.setattr(focus_worker, "build_scanner", lambda: FakeScanner())
    with TestClient(app.app) as client:
        box = OverlayBox(kind="phone", label="phone", confidence=0.81, x=0.4, y=0.5, width=0.1, height=0.2)
        app.worker.last_overlay = Overlay(at=time.time() - 2.0, frame_width=640, frame_height=480, boxes=[box])
        overlay = client.get("/api/focus", auth=AUTH).json()["overlay"]
        assert overlay["boxes"] == [{"kind": "phone", "label": "phone", "confidence": 0.81, "x": 0.4, "y": 0.5, "width": 0.1, "height": 0.2}]
        assert (overlay["frame_width"], overlay["frame_height"]) == (640, 480)
        assert 1.5 <= overlay["age_s"] <= 3.0
    assert app.worker is None
