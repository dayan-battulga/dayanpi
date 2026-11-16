import gc
import json
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
    monkeypatch.setattr(focus_worker, "build_hand_scanner", lambda: None)


def test_dashboard_runs_without_camera(caplog):
    with TestClient(app.app) as client:
        assert client.get("/api/health", auth=AUTH).status_code == 200
        assert app.stream._thread.is_alive()
    assert "camera unavailable at startup" in caplog.text


def test_dashboard_serves_every_file_it_links():
    """dayanpi/static/ is web/'s build: index.html, then hashed JS and CSS, and the fonts the CSS names."""
    with TestClient(app.app) as client:
        page = client.get("/", auth=AUTH)
        assert page.status_code == 200
        linked = re.findall(r'(?:src|href)="([^"#?]+)"', page.text)
        assert {path.rsplit(".", 1)[-1] for path in linked} == {"js", "css"}
        stylesheets = [client.get(path, auth=AUTH).text for path in linked if path.endswith(".css")]
        fonts = [path for css in stylesheets for path in re.findall(r"url\(([^)]+)\)", css)]
        assert any(path.endswith(".woff2") for path in fonts)
        for path in linked + fonts:
            # Nothing from the internet: the Pi serves every file the page needs.
            assert path.startswith("/assets/"), path
            response = client.get(path, auth=AUTH)
            assert response.status_code == 200, path
            assert response.headers["cache-control"] == "no-cache", path
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


@pytest.mark.parametrize(
    "site",
    [
        "https://youtube.com/watch?v=1",
        "youtube.com/watch",
        "YouTube.com",
        "my page title",
        "-bad.com",
        "bad-.com",
        "youtube..com",
        "",
        "a" * 254,
        "y" * 64 + ".com",
        123,
    ],
)
def test_the_mac_app_route_rejects_anything_but_a_plain_host_name(site):
    with TestClient(app.app) as client:
        assert client.post("/api/mac/app", json={"app": "Google Chrome", "site": site}, auth=AUTH).status_code == 422


def test_the_mac_app_route_takes_a_site_or_none_and_logs_it(monkeypatch, tmp_path):
    from dayanpi.focus.tracker import FocusLog, FocusTracker, format_day

    log = FocusLog(tmp_path / "focus_log")
    monkeypatch.setattr(app, "tracker", FocusTracker(log, started_at=time.time()))
    with TestClient(app.app) as client:
        chrome = client.post("/api/mac/app", json={"app": "Google Chrome", "site": "youtube.com"}, auth=AUTH)
        status = client.get("/api/focus", auth=AUTH).json()
        code = client.post("/api/mac/app", json={"app": "Code"}, auth=AUTH)
        local = client.post("/api/mac/app", json={"app": "Arc", "site": "localhost"}, auth=AUTH)
    assert [chrome.status_code, code.status_code, local.status_code] == [200, 200, 200]
    assert (status["app"], status["site"]) == ("Google Chrome", "youtube.com")
    lines = [(line["app"], line["site"]) for line in log.read_day(format_day(time.time())) if line["event"] == "mac_app"]
    assert lines == [("Google Chrome", "youtube.com"), ("Code", None), ("Arc", "localhost")]


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
        callouts=[focus.Callout("instant_pickup", "Already?"), focus.Callout("quiet", "Only for the log.", speak=False)],
    )
    app.handle_focus_update(update, time.time())
    assert said == ["Already?"]


def test_every_hand_sign_does_something():
    from dayanpi.vision.gestures import HAND_SIGNS

    assert set(HAND_SIGNS) == set(app.SIGN_ACTIONS)


def test_peace_speaks_the_coachs_message_and_logs_which_kind(monkeypatch, tmp_path):
    from dayanpi.focus.coach import TodoCoach
    from dayanpi.focus.todos import TodoList
    from dayanpi.focus.tracker import FocusLog, FocusTracker, format_day

    said = []
    log = FocusLog(tmp_path / "focus_log")
    todos = TodoList(tmp_path / "todos.json", log)
    monkeypatch.setattr(app, "coach", TodoCoach(todos, 0, None))
    monkeypatch.setattr(app, "tracker", FocusTracker(log, started_at=time.time()))
    monkeypatch.setattr(app.voice, "say", lambda text: said.append(text) or True)
    now = time.time()
    todos.add("finish the report", now)
    laundry = todos.add("do laundry", now)["id"]
    todos.add("reply to emails", now)
    todos.change(laundry, now, done=True)

    app.handle_gesture("peace", now)

    assert len(said) == 1
    assert "You have 2 things to do: finish the report and reply to emails. Done today: do laundry." in said[0]
    gestures = [line for line in log.read_day(format_day(now)) if line["event"] == "gesture"]
    assert [(line["name"], line["spoken"]) for line in gestures] == [("peace", "template")]


def test_the_coach_only_writes_ahead_with_a_model_set():
    with TestClient(app.app):
        assert app.coach.llm is None, "DAYANPI_LLM_MODEL isn't set in the tests"
        assert not app.coach.running


def test_focus_status_carries_the_last_gesture_and_its_age(monkeypatch):
    class FakeScanner:
        def scan(self, image):
            raise AssertionError("no frames here")

    monkeypatch.setattr(focus_worker, "build_scanner", lambda: FakeScanner())
    with TestClient(app.app) as client:
        assert client.get("/api/focus", auth=AUTH).json()["gesture"] is None
        app.worker.last_gesture = {"name": "peace", "at": time.time() - 2.0}
        gesture = client.get("/api/focus", auth=AUTH).json()["gesture"]
    assert gesture["name"] == "peace"
    assert 1.5 <= gesture["age_s"] <= 3.0


def test_todo_routes_add_edit_check_current_and_delete():
    with TestClient(app.app) as client:
        assert client.get("/api/todos").status_code == 401
        assert client.post("/api/todos", json={"text": "sneaky"}).status_code == 401
        added = client.post("/api/todos", json={"text": "  finish the report  "}, auth=AUTH).json()
        item_id = added["item"]["id"]
        assert added["item"]["text"] == "finish the report"
        path = f"/api/todos/{item_id}"
        assert client.patch(path, json={"done": True}).status_code == 401
        assert client.delete(path).status_code == 401
        assert client.patch(path, json={"text": "finish the big report"}, auth=AUTH).status_code == 200
        listed = client.patch(path, json={"current": True}, auth=AUTH).json()["todos"]
        assert listed["current"] == item_id
        listed = client.patch(path, json={"done": True}, auth=AUTH).json()["todos"]
        assert [item["text"] for item in listed["done"] if item["id"] == item_id] == ["finish the big report"]
        assert listed["current"] is None
        listed = client.patch(path, json={"done": False}, auth=AUTH).json()["todos"]
        assert item_id in [item["id"] for item in listed["open"]]
        assert client.get("/api/todos", auth=AUTH).json() == listed
        assert client.get("/api/focus", auth=AUTH).json()["todos"] == listed
        assert client.delete(path, auth=AUTH).status_code == 200
        assert client.delete(path, auth=AUTH).status_code == 404
        assert client.patch(path, json={"done": True}, auth=AUTH).status_code == 404
        assert client.post("/api/todos", json={"text": "   "}, auth=AUTH).status_code == 422
        assert client.post("/api/todos", json={"text": "x" * 201}, auth=AUTH).status_code == 422
        assert client.patch(path, json={"text": ""}, auth=AUTH).status_code == 422


def test_working_counts_time_for_the_current_todo():
    from dayanpi.focus.tracker import FocusUpdate

    now = time.time()
    item_id = app.todos.add("hook test", now)["id"]
    app.todos.change(item_id, now, current=True)
    for second in range(4):
        app.handle_focus_update(FocusUpdate(state="working"), now + second)
    for second in range(4, 8):
        app.handle_focus_update(FocusUpdate(state="phone"), now + second)
    open_items = app.todos.snapshot(now + 8)["open"]
    assert [item["seconds"] for item in open_items if item["id"] == item_id] == [4]
    app.todos.delete(item_id, now + 9)


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
    """The built page's feeds (FEEDS in web/src/components/camera/CameraCard.tsx) against the server:
    a typo in one would just be a dead feed or no boxes."""
    with TestClient(app.app) as client:
        page = client.get("/", auth=AUTH).text
        bundle = "".join(client.get(path, auth=AUTH).text for path in re.findall(r'src="([^"]+\.js)"', page))
        status = client.get("/api/focus", auth=AUTH).json()
    feed_paths = re.findall(r"src:[`\"'](/video[^`\"']*)", bundle)
    overlay_keys = re.findall(r"overlayKey:[`\"']([^`\"']+)", bundle)
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


def test_day_routes_serve_past_pages_and_build_today_live(monkeypatch, tmp_path):
    from dayanpi.focus.tracker import FocusLog, format_day

    log = FocusLog(tmp_path / "focus_log")
    monkeypatch.setattr(app, "focus_log", log)
    monkeypatch.setattr(app, "DAYS_DIR", tmp_path / "days")
    now = time.time()
    today = format_day(now)
    month = today[:7]
    past = f"{month}-01" if today != f"{month}-01" else f"{month}-02"
    (tmp_path / "days").mkdir()
    (tmp_path / "days" / f"{past}.md").write_text("---\nfocus_minutes: 95\n---\n\n# A past day\n")
    (tmp_path / "days" / "notes.md").write_text("not a day")
    log.write({"ts": now - 600, "day": today, "event": "state", "state": "working"})
    log.write({"ts": now, "day": today, "event": "sample"})

    with TestClient(app.app) as client:
        assert client.get(f"/api/days?month={month}").status_code == 401
        assert client.get(f"/api/days/{past}").status_code == 401
        listed = client.get(f"/api/days?month={month}", auth=AUTH).json()
        page = client.get(f"/api/days/{past}", auth=AUTH).json()
        live = client.get(f"/api/days/{today}", auth=AUTH).json()
        missing = client.get("/api/days/1999-01-01", auth=AUTH)
        bad_names = [client.get(f"/api/days/{name}", auth=AUTH).status_code for name in ("notes", "2026-11-1", "2026-11-014", "..%2F..%2Fdayanpi")]
        bad_month = client.get("/api/days?month=2026-1", auth=AUTH)

    assert listed["month"] == month and listed["today"] == today
    assert listed["days"][past] == {"focus_minutes": 95}
    assert listed["days"][today]["focus_minutes"] == 10, "today comes live from the log"
    assert page == {"day": past, "today": False, "markdown": "---\nfocus_minutes: 95\n---\n\n# A past day\n"}
    assert live["today"] is True and "- Focus: 10m" in live["markdown"]
    assert not (tmp_path / "days" / f"{today}.md").exists(), "today's page is never saved"
    assert missing.status_code == 404
    assert all(code in (404, 422) for code in bad_names)
    assert bad_names[:3] == [422, 422, 422]
    assert bad_month.status_code == 422


@pytest.fixture
def fresh_mac_tracking(monkeypatch, tmp_path):
    """Its own setting file and tracker, so one test switching it off can't leak into the next."""
    from dayanpi.focus.mac_tracking import MacTrackingSetting
    from dayanpi.focus.tracker import FocusLog, FocusTracker

    log = FocusLog(tmp_path / "focus_log")
    monkeypatch.setattr(app, "mac_tracking", MacTrackingSetting(tmp_path / "mac_tracking.json"))
    monkeypatch.setattr(app, "tracker", FocusTracker(log, started_at=time.time()))
    return log


def test_the_mac_tracking_switch_routes(fresh_mac_tracking, tmp_path):
    with TestClient(app.app) as client:
        assert client.get("/api/mac/tracking").status_code == 401
        assert client.post("/api/mac/tracking", json={"enabled": False}).status_code == 401
        assert client.get("/api/mac/tracking", auth=AUTH).json() == {"enabled": True}
        assert client.post("/api/mac/tracking", json={"enabled": False}, auth=AUTH).json() == {"enabled": False}
        assert client.get("/api/mac/tracking", auth=AUTH).json() == {"enabled": False}
        assert client.get("/api/focus", auth=AUTH).json()["mac_tracking"] is False
        bad = [client.post("/api/mac/tracking", json=body, auth=AUTH).status_code for body in ({}, {"enabled": "no"}, {"enabled": 1}, {"enabled": None})]
    assert bad == [422, 422, 422, 422]
    assert json.loads((tmp_path / "mac_tracking.json").read_text()) == {"enabled": False}


def test_reports_are_dropped_while_off_and_pausing_clears_the_current_app(fresh_mac_tracking):
    from dayanpi.focus.tracker import format_day

    with TestClient(app.app) as client:
        client.post("/api/mac/app", json={"app": "Google Chrome", "site": "youtube.com"}, auth=AUTH)
        client.post("/api/mac/tracking", json={"enabled": False}, auth=AUTH)
        cleared = client.get("/api/focus", auth=AUTH).json()
        dropped = client.post("/api/mac/app", json={"app": "Code"}, auth=AUTH)
        still_cleared = client.get("/api/focus", auth=AUTH).json()
        client.post("/api/mac/tracking", json={"enabled": True}, auth=AUTH)
        back = client.post("/api/mac/app", json={"app": "Code"}, auth=AUTH)
    assert (cleared["app"], cleared["site"]) == (None, None)
    assert dropped.status_code == 200
    assert dropped.json() == {"status": "ok", "changed": False, "enabled": False}
    assert still_cleared["app"] is None
    assert back.json() == {"status": "ok", "changed": True, "enabled": True}
    lines = [(line["event"], line.get("app"), line.get("enabled")) for line in fresh_mac_tracking.read_day(format_day(time.time())) if line["event"] in ("mac_app", "mac_tracking")]
    assert lines == [
        ("mac_app", "Google Chrome", None),
        ("mac_tracking", None, False),
        ("mac_tracking", None, True),
        ("mac_app", "Code", None),
    ]


def test_starting_up_switched_off_logs_that_it_is_paused(fresh_mac_tracking):
    from dayanpi.focus.tracker import format_day

    app.mac_tracking.set(False)
    with TestClient(app.app):
        pass
    lines = [line for line in fresh_mac_tracking.read_day(format_day(time.time())) if line["event"] == "mac_tracking"]
    assert [line["enabled"] for line in lines] == [False]
