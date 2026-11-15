import gc
import os
import re
import tempfile
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

os.environ.setdefault("DAYANPI_USER", "tester")
os.environ.setdefault("DAYANPI_PASSWORD", "secret")
os.environ.setdefault("DAYANPI_DATA_DIR", tempfile.mkdtemp(prefix="dayanpi-test-"))

from dayanpi import app  # noqa: E402  (auth env must be set before import)
from dayanpi.hardware import camera  # noqa: E402
from dayanpi.hardware import collector  # noqa: E402
from dayanpi.focus import worker as focus_worker  # noqa: E402

AUTH = (app.AUTH_USER, app.AUTH_PASSWORD)


@pytest.fixture(autouse=True)
def mac_friendly(monkeypatch):
    # No /proc, vcgencmd or /dev/video0 on the Mac, and no model loading per test.
    monkeypatch.setattr(app.sampler, "sample", lambda: None)
    monkeypatch.setattr(collector, "snapshot", lambda sampler: {"fake": True})
    monkeypatch.setattr(camera, "RECONNECT_SLEEP_S", 0.01)
    monkeypatch.setattr(focus_worker, "build_scanner", lambda: None)


def test_dashboard_runs_without_camera(caplog):
    with TestClient(app.app) as client:
        assert client.get("/api/health", auth=AUTH).status_code == 200
        assert app.stream._thread.is_alive()
    assert "camera unavailable at startup" in caplog.text


def test_dashboard_serves_every_file_it_links():
    with TestClient(app.app) as client:
        page = client.get("/", auth=AUTH)
        assert page.status_code == 200
        linked = re.findall(r'(?:src|href)="(/[^"#?]+)"', page.text)
        assert {"/styles.css", "/ui.js", "/app.js", "/focus.js"} <= set(linked)
        for path in linked:
            assert client.get(path, auth=AUTH).status_code == 200, path
        assert client.get("/", headers={}).status_code == 401


def test_focus_api_reports_disabled_without_models():
    with TestClient(app.app) as client:
        response = client.get("/api/focus", auth=AUTH)
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["state"] == "unknown"
        assert isinstance(body["segments"], list)
        assert client.get("/api/focus").status_code == 401


def test_stats_snapshot_carries_focus():
    with TestClient(app.app) as client:
        deadline = time.monotonic() + 3
        body = {}
        while "focus" not in body and time.monotonic() < deadline:
            body = client.get("/api/stats", auth=AUTH).json()
            time.sleep(0.05)
        assert body["fake"] is True
        assert body["focus"]["state"] == "unknown"
        assert "today" in body["focus"]


def test_mac_app_route_records_the_front_app():
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


def test_block_route_starts_stops_and_toggles():
    with TestClient(app.app) as client:
        assert client.post("/api/focus/block", json={"action": "stop"}, auth=AUTH).json()["active"] is False
        started = client.post("/api/focus/block", json={"action": "start"}, auth=AUTH).json()
        assert started == {"status": "ok", "active": True, "changed": True}
        assert client.get("/api/focus", auth=AUTH).json()["block"]["active"] is True
        toggled = client.post("/api/focus/block", json={"action": "toggle"}, auth=AUTH).json()
        assert toggled["active"] is False
        assert client.post("/api/focus/block", json={"action": "dance"}, auth=AUTH).status_code == 422


def test_focus_status_reports_the_voice():
    with TestClient(app.app) as client:
        status = client.get("/api/focus", auth=AUTH).json()
    assert status["voice"] == {"enabled": False, "backend": "off", "problem": None}


def test_callouts_reach_the_voice(monkeypatch):
    from dayanpi.focus import tracker as focus

    said = []
    monkeypatch.setattr(app.voice, "say", lambda text: said.append(text) or True)
    update = focus.FocusUpdate(
        state="phone",
        callouts=[focus.Callout("instant_pickup", "Already?"), focus.Callout("break_over", "Break's over.", speak=False)],
    )
    app.handle_focus_update(update, time.time())
    assert said == ["Already?"]


def test_gesture_toggles_the_block_and_speaks(monkeypatch):
    said = []
    monkeypatch.setattr(app.voice, "say", lambda text: said.append(text) or True)
    with TestClient(app.app) as client:
        client.post("/api/focus/block", json={"action": "stop"}, auth=AUTH)
        app.handle_gesture("toggle_block", time.time())
        assert client.get("/api/focus", auth=AUTH).json()["block"]["active"] is True
        app.handle_gesture("toggle_block", time.time())
        assert client.get("/api/focus", auth=AUTH).json()["block"]["active"] is False
    assert said == ["Block started.", "Block stopped."]


def test_sign_preview_renders_and_the_status_says_when_it_changes():
    with TestClient(app.app) as client:
        deadline = time.monotonic() + 3
        body = {"sign": {"version": 0}}
        while body["sign"]["version"] < 1 and time.monotonic() < deadline:
            body = client.get("/api/focus", auth=AUTH).json()
            time.sleep(0.05)
        assert body["sign"]["mode"] == "preview"
        assert body["sign"]["page"] == "now"
        assert body["sign"]["version"] >= 1
        stats = read_stats_focus(client)
        assert stats["sign"]["version"] >= 1
        response = client.get("/api/sign.png", auth=AUTH)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        # The version starts over when the service restarts, so an old picture must never come from cache.
        assert response.headers["cache-control"] == "no-store"
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert client.get("/api/sign.png").status_code == 401


def test_the_site_can_flip_the_sign_page():
    with TestClient(app.app) as client:
        assert client.post("/api/sign/page", json={"step": 1}).status_code == 401
        assert client.post("/api/sign/page", json={"step": 1}, auth=AUTH).json() == {"status": "ok", "page": "today"}
        assert client.post("/api/sign/page", json={"step": 1}, auth=AUTH).json()["page"] == "summary"
        assert client.post("/api/sign/page", json={"step": -1}, auth=AUTH).json()["page"] == "today"
        assert client.post("/api/sign/page", json={"step": 2}, auth=AUTH).status_code == 422
        assert client.get("/api/focus", auth=AUTH).json()["sign"]["page"] == "today"


def test_flipping_an_off_sign_says_so(monkeypatch):
    monkeypatch.setattr(app, "SIGN_MODE", "off")
    with TestClient(app.app) as client:
        response = client.post("/api/sign/page", json={"step": 1}, auth=AUTH)
        assert response.status_code == 503
        assert response.json()["detail"] == "Sign is off"


def test_callouts_and_gestures_reach_the_sign(monkeypatch):
    from dayanpi.focus import tracker as focus

    monkeypatch.setattr(app.voice, "say", lambda text: True)
    with TestClient(app.app):
        controller = app.sign_controller
        assert controller is not None
        app.handle_focus_update(
            focus.FocusUpdate(state="phone", callouts=[focus.Callout("break_over", "Break's over. Back to it.", speak=False)]),
            time.time(),
        )
        assert controller._queue or controller._active is not None
        app.handle_gesture("next_page", time.time())
        assert controller.page == "today"
        app.handle_gesture("previous_page", time.time())
        assert controller.page == "now"
    assert app.sign_controller is None


def test_panels_that_cannot_start_leave_the_preview_running(monkeypatch, caplog):
    import logging
    from dayanpi.sign import renderer as sign

    caplog.set_level(logging.INFO, logger="dayanpi.app")
    monkeypatch.setattr(app, "SIGN_MODE", "panel")
    monkeypatch.setattr(sign, "PanelOutput", lambda: (_ for _ in ()).throw(ImportError("no piomatter")))
    monkeypatch.setattr(app, "PanelOutput", lambda: (_ for _ in ()).throw(ImportError("no piomatter")))
    with TestClient(app.app):
        assert app.sign_controller is not None
    assert "panels unavailable, preview only" in caplog.text


def test_worker_runs_when_a_scanner_exists(monkeypatch):
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
        assert status["side_overlay"] is None
        assert app.worker.side is None


def test_the_worker_reads_the_side_camera_when_there_is_one(monkeypatch):
    side = FakeCamera()
    monkeypatch.setattr(app, "side_stream", side)
    monkeypatch.setattr(focus_worker, "build_scanner", lambda: object())
    with TestClient(app.app):
        assert app.worker.side.stream is side
        assert app.worker.front.stream is app.stream


def test_focus_status_carries_the_boxes_and_their_age(monkeypatch):
    class FakeScanner:
        def scan(self, image):
            raise AssertionError("no frames here")

    monkeypatch.setattr(focus_worker, "build_scanner", lambda: FakeScanner())
    with TestClient(app.app) as client:
        box = {"kind": "phone", "label": "phone", "confidence": 0.81, "x": 0.4, "y": 0.5, "width": 0.1, "height": 0.2}
        app.worker.last_overlay = {"at": time.time() - 2.0, "frame_width": 640, "frame_height": 480, "boxes": [box]}
        overlay = client.get("/api/focus", auth=AUTH).json()["overlay"]
        assert overlay["boxes"] == [{"kind": "phone", "label": "phone", "confidence": 0.81, "x": 0.4, "y": 0.5, "width": 0.1, "height": 0.2}]
        assert (overlay["frame_width"], overlay["frame_height"]) == (640, 480)
        assert 1.5 <= overlay["age_s"] <= 3.0
    assert app.worker is None


def test_focus_status_carries_the_side_boxes_and_their_age(monkeypatch):
    class FakeScanner:
        def scan(self, image):
            raise AssertionError("no frames here")

    monkeypatch.setattr(focus_worker, "build_scanner", lambda: FakeScanner())
    with TestClient(app.app) as client:
        box = {"kind": "phone", "label": "phone", "confidence": 0.7, "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
        app.worker.last_side_overlay = {"at": time.time() - 2.0, "frame_width": 640, "frame_height": 480, "boxes": [box]}
        status = client.get("/api/focus", auth=AUTH).json()
        assert status["overlay"] is None, "the side boxes must not land on the front feed"
        assert status["side_overlay"]["boxes"] == [box]
        assert 1.5 <= status["side_overlay"]["age_s"] <= 3.0


def test_focus_status_has_no_side_boxes_without_a_worker():
    with TestClient(app.app) as client:
        assert client.get("/api/focus", auth=AUTH).json()["side_overlay"] is None


class FakeCamera:
    """Hands out one frame, then nothing, so a video response ends by itself."""

    def __init__(self, jpeg: bytes = b"jpeg") -> None:
        self.frames = [jpeg]
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def frame_after(self, last_id: int, timeout: float):
        result = (self.frames.pop(), 1) if self.frames else None
        return result


def read_stats_focus(client):
    deadline = time.monotonic() + 3
    body = {}
    while "focus" not in body and time.monotonic() < deadline:
        body = client.get("/api/stats", auth=AUTH).json()
        time.sleep(0.05)
    return body["focus"]


def test_status_says_when_there_is_no_side_camera():
    with TestClient(app.app) as client:
        assert client.get("/api/focus", auth=AUTH).json()["side_camera"] is False
        assert read_stats_focus(client)["side_camera"] is False


def test_status_says_when_there_is_a_side_camera(monkeypatch):
    monkeypatch.setattr(app, "side_stream", FakeCamera())
    with TestClient(app.app) as client:
        assert client.get("/api/focus", auth=AUTH).json()["side_camera"] is True
        assert read_stats_focus(client)["side_camera"] is True


def test_the_dashboard_feeds_match_the_server():
    """No JS tests here, so a typo in one of these would just be a dead feed or no boxes."""
    with TestClient(app.app) as client:
        page = client.get("/", auth=AUTH).text
        status = client.get("/api/focus", auth=AUTH).json()
    feed_paths = re.findall(r'data-feed="([^"]+)"', page)
    overlay_keys = re.findall(r'data-overlay-key="([^"]+)"', page)
    assert len(feed_paths) == len(overlay_keys) == 2
    assert set(feed_paths) <= {route.path for route in app.app.routes}
    assert set(overlay_keys) <= set(status)


class EndlessCamera:
    """Always has a newer frame, like a healthy camera."""

    def __init__(self) -> None:
        self.frame_id = 0

    def frame_after(self, last_id: int, timeout: float):
        time.sleep(0.01)
        self.frame_id += 1
        result = (b"jpeg", self.frame_id)
        return result


@pytest.fixture
def real_server(monkeypatch):
    """A real uvicorn, because a viewer hanging up mid-stream is what TestClient can't do."""
    camera = EndlessCamera()
    monkeypatch.setattr(app, "stream", camera)
    monkeypatch.setattr(app, "side_stream", camera)
    server = uvicorn.Server(uvicorn.Config(app.app, host="127.0.0.1", port=0, lifespan="off", log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    # With the collector off, a slot that only comes back through garbage collection never comes back.
    gc.disable()
    yield f"http://127.0.0.1:{port}"
    gc.enable()
    server.should_exit = True
    thread.join(5)


@pytest.mark.parametrize(
    "path, slots_name",
    [("/video", "_video_slots"), ("/video/side", "_side_video_slots"), ("/api/stream", "_stream_slots")],
)
def test_a_viewer_who_leaves_gives_the_slot_back_right_away(real_server, path, slots_name):
    slots = getattr(app, slots_name)
    all_free = slots._value
    for _ in range(all_free + 1):
        with httpx.stream("GET", real_server + path, auth=AUTH, timeout=3) as response:
            assert response.status_code == 200
            next(response.iter_raw())
            assert slots._value == all_free - 1
        deadline = time.monotonic() + 2
        while slots._value < all_free and time.monotonic() < deadline:
            time.sleep(0.01)
        assert slots._value == all_free


def test_side_video_is_a_404_without_a_side_camera():
    with TestClient(app.app) as client:
        assert app.side_stream is None
        assert client.get("/video/side", auth=AUTH).status_code == 404
        assert client.get("/video/side").status_code == 401


def test_each_video_route_serves_its_own_camera(monkeypatch):
    monkeypatch.setattr(app, "stream", FakeCamera(b"front-jpeg"))
    monkeypatch.setattr(app, "side_stream", FakeCamera(b"side-jpeg"))
    with TestClient(app.app) as client:
        front = client.get("/video", auth=AUTH)
        side = client.get("/video/side", auth=AUTH)
        assert client.get("/video/side").status_code == 401
    assert b"front-jpeg" in front.content and b"side-jpeg" not in front.content
    assert b"side-jpeg" in side.content and b"front-jpeg" not in side.content
    assert side.headers["content-type"] == front.headers["content-type"]
    assert side.headers["content-type"].startswith("multipart/x-mixed-replace")


@pytest.mark.parametrize(
    ("full_route", "full_slots", "open_route"),
    [("/video", "_video_slots", "/video/side"), ("/video/side", "_side_video_slots", "/video")],
)
def test_a_full_feed_does_not_lock_out_the_other(monkeypatch, full_route, full_slots, open_route):
    monkeypatch.setattr(app, "side_stream", FakeCamera())
    monkeypatch.setattr(app, "frame_generator", lambda camera: iter([b"frame"]))
    slots = getattr(app, full_slots)
    with TestClient(app.app) as client:
        held = [slots.acquire(blocking=False) for _ in range(app.VIDEO_MAX_CONCURRENT)]
        assert all(held)
        try:
            assert client.get(full_route, auth=AUTH).status_code == 503
            assert client.get(open_route, auth=AUTH).status_code == 200
        finally:
            for _ in held:
                slots.release()


def test_the_side_camera_starts_and_stops_with_the_service(monkeypatch):
    side = FakeCamera()
    monkeypatch.setattr(app, "side_stream", side)
    with TestClient(app.app):
        assert side.running is True
    assert side.running is False


def test_video_frees_its_slot_and_turns_away_viewers_past_the_cap(monkeypatch):
    monkeypatch.setattr(app, "frame_generator", lambda camera: iter([b"frame"]))
    with TestClient(app.app) as client:
        for _ in range(app.VIDEO_MAX_CONCURRENT):
            assert client.get("/video", auth=AUTH).status_code == 200
        held = [app._video_slots.acquire(blocking=False) for _ in range(app.VIDEO_MAX_CONCURRENT)]
        assert all(held)
        try:
            assert client.get("/video", auth=AUTH).status_code == 503
        finally:
            for _ in held:
                app._video_slots.release()


def test_every_response_refuses_to_be_framed():
    with TestClient(app.app) as client:
        responses = [client.get("/api/health", auth=AUTH), client.get("/", auth=AUTH), client.get("/api/health")]
        assert [response.status_code for response in responses] == [200, 200, 401]
        assert all(response.headers["x-frame-options"] == "DENY" for response in responses)
