import gc
import json
import logging
import os
import re
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager
from urllib.parse import quote

import anyio
import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

os.environ.setdefault("DAYANPI_USER", "tester")
os.environ.setdefault("DAYANPI_PASSWORD", "secret")
os.environ.setdefault("DAYANPI_DATA_DIR", tempfile.mkdtemp(prefix="dayanpi-test-"))

from dayanpi import app  # noqa: E402  (auth env must be set before import)
from dayanpi.auth import routes as auth_routes  # noqa: E402
from dayanpi.auth.accounts import SESSION_TTL_S, AccountStore, LoginLockout  # noqa: E402
from dayanpi.hardware import camera  # noqa: E402
from dayanpi.hardware import collector  # noqa: E402
from dayanpi.focus import worker as focus_worker  # noqa: E402

AUTH = (app.AUTH_USER, app.AUTH_PASSWORD)
BASE_URL = "https://testserver"  # the session cookie is Secure, so an http client would never send it back
COOKIE = auth_routes.SESSION_COOKIE
MEMBER_PASSWORD = "member password"
MY_LOGIN = "dayan@example.com"


@pytest.fixture(autouse=True)
def mac_friendly(monkeypatch):
    # No /proc, vcgencmd or /dev/video0 on the Mac, and no model loading per test.
    monkeypatch.setattr(app.sampler, "sample", lambda: None)
    monkeypatch.setattr(collector, "snapshot", lambda sampler: {"fake": True})
    monkeypatch.setattr(camera, "RECONNECT_SLEEP_S", 0.01)
    monkeypatch.setattr(focus_worker, "build_scanner", lambda: None)
    monkeypatch.setattr(focus_worker, "build_hand_scanner", lambda: None)


@pytest.fixture(autouse=True)
def fresh_accounts(monkeypatch, tmp_path):
    """Its own accounts.db and lockout per test, and the camera lock off unless a test turns it on."""
    monkeypatch.setattr(auth_routes, "accounts", AccountStore(tmp_path / "accounts.db"))
    monkeypatch.setattr(auth_routes, "lockout", LoginLockout())
    monkeypatch.setattr(auth_routes, "password_lockout", LoginLockout())
    monkeypatch.setattr(auth_routes, "TAILSCALE_LOGIN", "")


def find_owner():
    """The owner from DAYANPI_USER, made here if no app startup has made it yet."""
    auth_routes.accounts.seed_owner(*AUTH, time.time())
    owner = next(user for user in auth_routes.accounts.list_users() if user.role == "owner")
    return owner


def add_member(username="bo"):
    find_owner()  # the owner always comes first; after a member, seeding would do nothing
    now = time.time()
    invite = auth_routes.accounts.create_invite(now)
    member = auth_routes.accounts.join(invite.code, username.title(), username, MEMBER_PASSWORD, now)
    return member


def let_in(client, user):
    """Signs a client in straight through the store, so tests don't pay for scrypt on every sign-in."""
    client.cookies.set(COOKIE, auth_routes.accounts.create_session(user.id, time.time()))
    return client


def stranger(**options):
    """A client without the app's startup, for a second viewer next to an open_client()."""
    client = TestClient(app.app, base_url=BASE_URL, **options)
    return client


@contextmanager
def open_client(role="owner", **options):
    """The app with its startup and shutdown, signed in as the owner, a new member, or nobody (None)."""
    with TestClient(app.app, base_url=BASE_URL, **options) as client:
        if role is not None:
            let_in(client, find_owner() if role == "owner" else add_member())
        yield client


def delete(client, path):
    """Every write sends JSON, DELETE included."""
    response = client.request("DELETE", path, json={})
    return response


def list_routes(routes):
    """FastAPI keeps an included router as one entry, so this opens it up."""
    found = []
    for route in routes:
        found += list_routes(route.original_router.routes) if hasattr(route, "original_router") else [route]
    return found


def test_dashboard_runs_without_camera(caplog):
    with open_client() as client:
        assert client.get("/api/health").status_code == 200
        assert app.stream._thread.is_alive()
    assert "camera unavailable at startup" in caplog.text


def test_dashboard_serves_every_file_it_links():
    """dayanpi/static/ is web/'s build: index.html, then hashed JS and CSS, and the fonts the CSS names."""
    with open_client() as client:
        page = client.get("/")
        assert page.status_code == 200
        linked = re.findall(r'(?:src|href)="([^"#?]+)"', page.text)
        assert {path.rsplit(".", 1)[-1] for path in linked} == {"js", "css"}
        stylesheets = [client.get(path).text for path in linked if path.endswith(".css")]
        fonts = [path for css in stylesheets for path in re.findall(r"url\(([^)]+)\)", css)]
        assert any(path.endswith(".woff2") for path in fonts)
        for path in linked + fonts:
            # Nothing from the internet: the Pi serves every file the page needs.
            assert path.startswith("/assets/"), path
            response = stranger().get(path)
            assert response.status_code == 200, f"the sign-in page needs {path} before anyone signs in"
            assert response.headers["cache-control"] == "no-cache", path
        signed_out = stranger().get("/", follow_redirects=False)
    assert (signed_out.status_code, signed_out.headers["location"]) == (303, "/login?next=%2F")


def test_focus_api_reports_disabled_without_models():
    with open_client() as client:
        response = client.get("/api/focus")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["state"] == "unknown"
        assert isinstance(body["segments"], list)
        assert stranger().get("/api/focus").status_code == 401


def test_stats_snapshot_carries_focus():
    with open_client() as client:
        deadline = time.monotonic() + 3
        body = {}
        while "focus" not in body and time.monotonic() < deadline:
            body = client.get("/api/stats").json()
            time.sleep(0.05)
        assert body["fake"] is True
        assert body["focus"]["state"] == "unknown"
        assert "today" in body["focus"]


def test_mac_app_route_records_the_front_app():
    with open_client() as client:
        first = client.post("/api/mac/app", json={"app": "  Code "})
        assert first.status_code == 200
        assert first.json()["changed"] is True
        again = client.post("/api/mac/app", json={"app": "Code"})
        assert again.json()["changed"] is False
        assert client.get("/api/focus").json()["app"] == "Code"
        assert client.post("/api/mac/app", json={"app": ""}).status_code == 422
        assert client.post("/api/mac/app", json={"app": "x" * 101}).status_code == 422


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
    with open_client() as client:
        assert client.post("/api/mac/app", json={"app": "Google Chrome", "site": site}).status_code == 422


def test_the_mac_app_route_takes_a_site_or_none_and_logs_it(monkeypatch, tmp_path):
    from dayanpi.focus.tracker import FocusLog, FocusTracker, format_day

    log = FocusLog(tmp_path / "focus_log")
    monkeypatch.setattr(app, "tracker", FocusTracker(log, started_at=time.time()))
    with open_client() as client:
        chrome = client.post("/api/mac/app", json={"app": "Google Chrome", "site": "youtube.com"})
        status = client.get("/api/focus").json()
        code = client.post("/api/mac/app", json={"app": "Code"})
        local = client.post("/api/mac/app", json={"app": "Arc", "site": "localhost"})
    assert [chrome.status_code, code.status_code, local.status_code] == [200, 200, 200]
    assert (status["app"], status["site"]) == ("Google Chrome", "youtube.com")
    lines = [(line["app"], line["site"]) for line in log.read_day(format_day(time.time())) if line["event"] == "mac_app"]
    assert lines == [("Google Chrome", "youtube.com"), ("Code", None), ("Arc", "localhost")]


def test_focus_status_reports_the_voice():
    with open_client() as client:
        status = client.get("/api/focus").json()
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
    with open_client() as client:
        assert client.get("/api/focus").json()["gesture"] is None
        app.worker.last_gesture = {"name": "peace", "at": time.time() - 2.0}
        gesture = client.get("/api/focus").json()["gesture"]
    assert gesture["name"] == "peace"
    assert 1.5 <= gesture["age_s"] <= 3.0


def test_todo_routes_add_edit_check_current_and_delete():
    with open_client() as client:
        assert stranger().get("/api/todos").status_code == 401
        assert stranger().post("/api/todos", json={"text": "sneaky"}).status_code == 401
        added = client.post("/api/todos", json={"text": "  finish the report  "}).json()
        item_id = added["item"]["id"]
        assert added["item"]["text"] == "finish the report"
        path = f"/api/todos/{item_id}"
        assert stranger().patch(path, json={"done": True}).status_code == 401
        assert delete(stranger(), path).status_code == 401
        assert client.patch(path, json={"text": "finish the big report"}).status_code == 200
        listed = client.patch(path, json={"current": True}).json()["todos"]
        assert listed["current"] == item_id
        listed = client.patch(path, json={"done": True}).json()["todos"]
        assert [item["text"] for item in listed["done"] if item["id"] == item_id] == ["finish the big report"]
        assert listed["current"] is None
        listed = client.patch(path, json={"done": False}).json()["todos"]
        assert item_id in [item["id"] for item in listed["open"]]
        assert client.get("/api/todos").json() == listed
        assert client.get("/api/focus").json()["todos"] == listed
        assert delete(client, path).status_code == 200
        assert delete(client, path).status_code == 404
        assert client.patch(path, json={"done": True}).status_code == 404
        assert client.post("/api/todos", json={"text": "   "}).status_code == 422
        assert client.post("/api/todos", json={"text": "x" * 201}).status_code == 422
        assert client.patch(path, json={"text": ""}).status_code == 422


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
    with open_client() as client:
        assert app.worker is not None
        assert app.worker.running
        status = client.get("/api/focus").json()
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
    with open_client() as client:
        box = {"kind": "phone", "label": "phone", "confidence": 0.81, "x": 0.4, "y": 0.5, "width": 0.1, "height": 0.2}
        app.worker.last_overlay = {"at": time.time() - 2.0, "frame_width": 640, "frame_height": 480, "boxes": [box]}
        overlay = client.get("/api/focus").json()["overlay"]
        assert overlay["boxes"] == [{"kind": "phone", "label": "phone", "confidence": 0.81, "x": 0.4, "y": 0.5, "width": 0.1, "height": 0.2}]
        assert (overlay["frame_width"], overlay["frame_height"]) == (640, 480)
        assert 1.5 <= overlay["age_s"] <= 3.0
    assert app.worker is None


def test_focus_status_carries_the_side_boxes_and_their_age(monkeypatch):
    class FakeScanner:
        def scan(self, image):
            raise AssertionError("no frames here")

    monkeypatch.setattr(focus_worker, "build_scanner", lambda: FakeScanner())
    with open_client() as client:
        box = {"kind": "phone", "label": "phone", "confidence": 0.7, "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
        app.worker.last_side_overlay = {"at": time.time() - 2.0, "frame_width": 640, "frame_height": 480, "boxes": [box]}
        status = client.get("/api/focus").json()
        assert status["overlay"] is None, "the side boxes must not land on the front feed"
        assert status["side_overlay"]["boxes"] == [box]
        assert 1.5 <= status["side_overlay"]["age_s"] <= 3.0


def test_focus_status_has_no_side_boxes_without_a_worker():
    with open_client() as client:
        assert client.get("/api/focus").json()["side_overlay"] is None


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
        body = client.get("/api/stats").json()
        time.sleep(0.05)
    return body["focus"]


def test_status_says_when_there_is_no_side_camera():
    with open_client() as client:
        assert client.get("/api/focus").json()["side_camera"] is False
        assert read_stats_focus(client)["side_camera"] is False


def test_status_says_when_there_is_a_side_camera(monkeypatch):
    monkeypatch.setattr(app, "side_stream", FakeCamera())
    with open_client() as client:
        assert client.get("/api/focus").json()["side_camera"] is True
        assert read_stats_focus(client)["side_camera"] is True


def test_the_dashboard_feeds_match_the_server():
    """The built page's feeds (FEEDS in web/src/components/camera/CameraCard.tsx) against the server:
    a typo in one would just be a dead feed or no boxes. The camera is on the lazy /pi page, a chunk
    index.html doesn't name, so this reads every built script."""
    with open_client() as client:
        bundle = "".join(client.get(f"/assets/{path.name}").text for path in (app.STATIC_DIR / "assets").glob("*.js"))
        status = client.get("/api/focus").json()
    feed_paths = re.findall(r"src:[`\"'](/video[^`\"']*)", bundle)
    overlay_keys = re.findall(r"overlayKey:[`\"']([^`\"']+)", bundle)
    assert len(feed_paths) == len(overlay_keys) == 2
    assert set(feed_paths) <= {route.path for route in list_routes(app.app.routes)}
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


def session_header(user) -> dict:
    """The real server below is plain http, where a client won't send a Secure cookie back by itself."""
    header = {"Cookie": f"{COOKIE}={auth_routes.accounts.create_session(user.id, time.time())}"}
    return header


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
    "path, find_slots",
    [
        ("/video", lambda owner: app._video_slots),
        ("/video/side", lambda owner: app._side_video_slots),
        ("/api/stream", lambda owner: app._stream_slots[owner.id]),
    ],
)
def test_a_viewer_who_leaves_gives_the_slot_back_right_away(real_server, path, find_slots):
    owner = find_owner()
    slots = find_slots(owner)
    all_free = slots._value
    headers = session_header(owner)
    for _ in range(all_free + 1):
        with httpx.stream("GET", real_server + path, headers=headers, timeout=3) as response:
            assert response.status_code == 200
            next(response.iter_raw())
            assert slots._value == all_free - 1
        deadline = time.monotonic() + 2
        while slots._value < all_free and time.monotonic() < deadline:
            time.sleep(0.01)
        assert slots._value == all_free


def read_events(response, count: int) -> list[dict]:
    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
        if len(events) == count:
            break
    return events


def test_a_member_streams_only_the_focus_status(real_server, monkeypatch):
    box = {"kind": "phone", "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
    snapshot = {"temp_c": 51.0, "throttled": {"under_voltage": False}, "focus": {"state": "working", "overlay": {"boxes": [box]}, "side_overlay": None}}
    monkeypatch.setattr(app, "latest_snapshot", snapshot)
    with httpx.stream("GET", real_server + "/api/stream", headers=session_header(add_member()), timeout=3) as response:
        [member_event] = read_events(response, 1)
    with httpx.stream("GET", real_server + "/api/stream", headers=session_header(find_owner()), timeout=3) as response:
        [owner_event] = read_events(response, 1)
    assert member_event == {"focus": {"state": "working", "overlay": None, "side_overlay": None, "camera_access": "owner_only"}}
    assert owner_event == {**snapshot, "focus": {**snapshot["focus"], "camera_access": "open"}}
    assert "camera_access" not in app.latest_snapshot["focus"], "each viewer's copy, never the shared snapshot"


@pytest.mark.parametrize("ending", ["account removed", "signed out"])
def test_the_stream_stops_once_the_session_is_gone(real_server, ending):
    member = add_member()
    headers = session_header(member)
    with httpx.stream("GET", real_server + "/api/stream", headers=headers, timeout=3) as response:
        assert response.status_code == 200
        lines = response.iter_lines()
        assert next(lines) == "retry: 5000"
        if ending == "account removed":
            auth_routes.accounts.delete_member(member.id)
        else:
            httpx.post(real_server + "/api/logout", headers=headers, json={})
        deadline = time.monotonic() + 5
        for _ in lines:
            assert time.monotonic() < deadline, "the stream kept going without a session"


@pytest.mark.parametrize("path", ["/video", "/video/side"])
@pytest.mark.parametrize("ending", ["signed out", "password changed elsewhere"])
def test_a_camera_feed_stops_once_the_session_is_gone(real_server, path, ending):
    owner = find_owner()
    headers = session_header(owner)
    with httpx.stream("GET", real_server + path, headers=headers, timeout=3) as response:
        assert response.status_code == 200
        chunks = response.iter_raw()
        next(chunks)
        if ending == "signed out":
            httpx.post(real_server + "/api/logout", headers=headers, json={})
        else:
            other = auth_routes.accounts.create_session(owner.id, time.time())
            auth_routes.accounts.change_password(owner.id, AUTH[1], auth_routes.accounts.find_session(other, time.time()).token_hash)
        deadline = time.monotonic() + 5
        for _ in chunks:
            assert time.monotonic() < deadline, "the feed kept going without a session"


def test_a_members_streams_leave_the_owner_theirs(real_server):
    member = add_member()
    member_headers = session_header(member)
    with ExitStack() as held:
        for _ in range(app.STREAM_MAX_CONCURRENT):
            response = held.enter_context(httpx.stream("GET", real_server + "/api/stream", headers=member_headers, timeout=3))
            assert response.status_code == 200
        one_too_many = httpx.get(real_server + "/api/stream", headers=member_headers, timeout=3)
        with httpx.stream("GET", real_server + "/api/stream", headers=session_header(find_owner()), timeout=3) as owner:
            owner_status = owner.status_code
    assert (one_too_many.status_code, owner_status) == (503, 200)
    slots = app._stream_slots[member.id]
    deadline = time.monotonic() + 3
    while slots._value < app.STREAM_MAX_CONCURRENT and time.monotonic() < deadline:
        time.sleep(0.01)
    assert slots._value == app.STREAM_MAX_CONCURRENT


def test_side_video_is_a_404_without_a_side_camera():
    with open_client() as client:
        assert app.side_stream is None
        assert client.get("/video/side").status_code == 404
        assert stranger().get("/video/side").status_code == 401


def test_each_video_route_serves_its_own_camera(monkeypatch):
    monkeypatch.setattr(app, "stream", FakeCamera(b"front-jpeg"))
    monkeypatch.setattr(app, "side_stream", FakeCamera(b"side-jpeg"))
    with open_client() as client:
        front = client.get("/video")
        side = client.get("/video/side")
        assert stranger().get("/video/side").status_code == 401
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
    monkeypatch.setattr(app, "frame_generator", lambda camera, token: iter([b"frame"]))
    slots = getattr(app, full_slots)
    with open_client() as client:
        held = [slots.acquire(blocking=False) for _ in range(app.VIDEO_MAX_CONCURRENT)]
        assert all(held)
        try:
            assert client.get(full_route).status_code == 503
            assert client.get(open_route).status_code == 200
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
    monkeypatch.setattr(app, "frame_generator", lambda camera, token: iter([b"frame"]))
    with open_client() as client:
        for _ in range(app.VIDEO_MAX_CONCURRENT):
            assert client.get("/video").status_code == 200
        held = [app._video_slots.acquire(blocking=False) for _ in range(app.VIDEO_MAX_CONCURRENT)]
        assert all(held)
        try:
            assert client.get("/video").status_code == 503
        finally:
            for _ in held:
                app._video_slots.release()


def test_every_response_refuses_to_be_framed_and_sends_no_referrer():
    with open_client() as client:
        responses = [client.get("/api/health"), client.get("/"), stranger().get("/api/stats"), stranger().get("/join/abc")]
        assert [response.status_code for response in responses] == [200, 200, 401, 200]
        assert all(response.headers["x-frame-options"] == "DENY" for response in responses)
        assert all(response.headers["referrer-policy"] == "no-referrer" for response in responses)


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

    with open_client() as client:
        assert stranger().get(f"/api/days?month={month}").status_code == 401
        assert stranger().get(f"/api/days/{past}").status_code == 401
        listed = client.get(f"/api/days?month={month}").json()
        page = client.get(f"/api/days/{past}").json()
        live = client.get(f"/api/days/{today}").json()
        missing = client.get("/api/days/1999-01-01")
        bad_names = [client.get(f"/api/days/{name}").status_code for name in ("notes", "2026-11-1", "2026-11-014", "..%2F..%2Fdayanpi")]
        bad_month = client.get("/api/days?month=2026-1")

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
    with open_client() as client:
        assert stranger().get("/api/mac/tracking").status_code == 401
        assert stranger().post("/api/mac/tracking", json={"enabled": False}).status_code == 401
        assert client.get("/api/mac/tracking").json() == {"enabled": True}
        assert client.post("/api/mac/tracking", json={"enabled": False}).json() == {"enabled": False}
        assert client.get("/api/mac/tracking").json() == {"enabled": False}
        assert client.get("/api/focus").json()["mac_tracking"] is False
        bad = [client.post("/api/mac/tracking", json=body).status_code for body in ({}, {"enabled": "no"}, {"enabled": 1}, {"enabled": None})]
    assert bad == [422, 422, 422, 422]
    assert json.loads((tmp_path / "mac_tracking.json").read_text()) == {"enabled": False}


def test_reports_are_dropped_while_off_and_pausing_clears_the_current_app(fresh_mac_tracking):
    from dayanpi.focus.tracker import format_day

    with open_client() as client:
        client.post("/api/mac/app", json={"app": "Google Chrome", "site": "youtube.com"})
        client.post("/api/mac/tracking", json={"enabled": False})
        cleared = client.get("/api/focus").json()
        dropped = client.post("/api/mac/app", json={"app": "Code"})
        still_cleared = client.get("/api/focus").json()
        client.post("/api/mac/tracking", json={"enabled": True})
        back = client.post("/api/mac/app", json={"app": "Code"})
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


def write_app_samples(log, day: str, ts: float, app_name: str, count: int, site=None, state="working") -> None:
    for index in range(count):
        log.write({"ts": ts + index, "day": day, "event": "sample", "state": state, "app": app_name, "site": site})


def test_apps_route_ranks_the_top_eight_and_sums_the_rest(monkeypatch, tmp_path):
    from dayanpi.focus.tracker import FocusLog, format_day

    log = FocusLog(tmp_path / "focus_log")
    monkeypatch.setattr(app, "focus_log", log)
    now = time.time()
    today = format_day(now)
    for index in range(9):  # App 0 has 1 sample ... App 8 has 9
        write_app_samples(log, today, now - 5000, f"App {index}", index + 1)
    write_app_samples(log, today, now - 4000, "Chrome", 20, "youtube.com")
    write_app_samples(log, today, now - 3000, "Chrome", 5, "github.com")
    write_app_samples(log, today, now - 2000, "Tie A", 9)
    write_app_samples(log, today, now - 1000, "Away App", 50, state="away")

    with open_client() as client:
        assert stranger().get("/api/apps").status_code == 401
        reply = client.get("/api/apps?range=today").json()
        default = client.get("/api/apps").json()
        bad = client.get("/api/apps?range=month")

    assert default == reply and reply["range"] == "today" and bad.status_code == 422
    names = [row["app"] for row in reply["apps"]]
    assert names == ["Chrome", "App 8", "Tie A", "App 7", "App 6", "App 5", "App 4", "App 3", "Other apps"]
    assert reply["apps"][0] == {"app": "Chrome", "total_seconds": 750.0, "youtube_seconds": 600.0, "other_sites_seconds": 150.0}
    assert reply["apps"][1] == {"app": "App 8", "total_seconds": 270.0}, "no site, so no split fields"
    assert reply["apps"][-1] == {"app": "Other apps", "total_seconds": 3 * 30.0 + 2 * 30 + 1 * 30}, "App 2, App 1, App 0"


def test_apps_route_week_sums_seven_days_and_ignores_the_eighth(monkeypatch, tmp_path):
    from datetime import datetime, timedelta

    from dayanpi.focus.tracker import FocusLog

    log = FocusLog(tmp_path / "focus_log")
    monkeypatch.setattr(app, "focus_log", log)
    now = time.time()
    today = datetime.fromtimestamp(now).date()
    for offset, samples in ((0, 2), (3, 4), (6, 1), (7, 100)):
        day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        write_app_samples(log, day, now - 1000, "Cursor", samples)
        write_app_samples(log, day, now - 500, "Arc", 1, "youtube.com")

    with open_client() as client:
        week = client.get("/api/apps?range=week").json()
        today_only = client.get("/api/apps?range=today").json()

    assert week["range"] == "week"
    assert week["apps"] == [
        {"app": "Cursor", "total_seconds": 7 * 30.0},
        {"app": "Arc", "total_seconds": 3 * 30.0, "youtube_seconds": 3 * 30.0, "other_sites_seconds": 0.0},
    ]
    assert today_only["apps"][0] == {"app": "Cursor", "total_seconds": 60.0}


def test_apps_route_on_an_empty_day_has_no_apps(monkeypatch, tmp_path):
    from dayanpi.focus.tracker import FocusLog

    monkeypatch.setattr(app, "focus_log", FocusLog(tmp_path / "focus_log"))
    with open_client() as client:
        assert client.get("/api/apps?range=week").json() == {"range": "week", "apps": []}


# Accounts, sessions and who may do what.


def test_the_first_start_makes_the_owner_and_later_starts_do_not(caplog):
    with caplog.at_level(logging.INFO):
        with TestClient(app.app):
            pass
        with TestClient(app.app):
            pass
    users = auth_routes.accounts.list_users()
    assert [(user.username, user.role) for user in users] == [(AUTH[0].strip().lower(), "owner")]
    assert caplog.text.count("made the owner account") == 1


@pytest.mark.parametrize("name", ["AUTH_USER", "AUTH_PASSWORD"])
def test_startup_still_needs_the_env_login(monkeypatch, name):
    monkeypatch.setattr(app, name, "")
    with pytest.raises(RuntimeError, match="DAYANPI_USER and DAYANPI_PASSWORD"):
        with TestClient(app.app):
            pass


def test_signing_in_sets_a_locked_down_session_cookie():
    with open_client(None) as client:
        response = client.post("/api/login", json={"username": f" {AUTH[0].upper()} ", "password": AUTH[1]})
        me = client.get("/api/me")
    assert response.status_code == 200
    user = response.json()["user"]
    assert set(user) == {"id", "username", "display_name", "role"}
    assert (user["username"], user["role"]) == (AUTH[0].strip().lower(), "owner")
    assert me.json() == {"user": user}
    cookie = response.headers["set-cookie"]
    name, _, value = cookie.split(";")[0].partition("=")
    flags = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert name == COOKIE and len(value) >= 40
    assert {"httponly", "secure", "samesite=lax", "path=/", f"max-age={int(SESSION_TTL_S)}"} <= flags
    assert not any(flag.startswith("domain") for flag in flags)
    assert value not in json.dumps(response.json())


def test_signing_out_ends_the_session_and_clears_the_cookie():
    with open_client(None) as client:
        client.post("/api/login", json={"username": AUTH[0], "password": AUTH[1]})
        token = client.cookies[COOKIE]
        out = client.post("/api/logout", json={})
        after = client.get("/api/me")
    replayed = stranger()
    replayed.cookies.set(COOKIE, token)
    assert out.json() == {"status": "ok"}
    assert "max-age=0" in out.headers["set-cookie"].lower()
    assert after.status_code == 401
    assert replayed.get("/api/me").status_code == 401, "the old cookie is dead on the Pi too"
    assert stranger().post("/api/logout", json={}).status_code == 200, "open without a session"


def test_a_session_is_refreshed_at_most_once_an_hour_and_expires():
    owner = find_owner()
    token = auth_routes.accounts.create_session(owner.id, time.time() - 2 * 3600)
    stale = stranger(cookies={COOKIE: token}).get("/api/me")
    fresh = stranger(cookies={COOKIE: token}).get("/api/me")
    session = auth_routes.accounts.find_session(token, time.time())
    expired = stranger()
    expired.cookies.set(COOKIE, auth_routes.accounts.create_session(owner.id, time.time() - SESSION_TTL_S - 1))
    assert stale.status_code == 200 and stale.headers["set-cookie"].startswith(f"{COOKIE}={token};")
    assert fresh.status_code == 200 and "set-cookie" not in fresh.headers
    assert time.time() - session.extended_at < 60
    assert expired.get("/api/me").status_code == 401


def test_a_removed_member_is_signed_out_everywhere():
    with open_client() as owner:
        member = add_member()
        member_client = let_in(stranger(), member)
        mac = auth_routes.accounts.create_token(member.id, "mac", time.time())
        assert member_client.get("/api/me").status_code == 200
        listed = owner.get("/api/accounts").json()["accounts"]
        removed = delete(owner, f"/api/accounts/{member.id}")
        own = delete(owner, f"/api/accounts/{find_owner().id}")
        unknown = delete(owner, "/api/accounts/999")
        after = owner.get("/api/accounts").json()["accounts"]
    assert [(account["username"], account["role"]) for account in listed] == [(AUTH[0].lower(), "owner"), ("bo", "member")]
    assert set(listed[1]) == {"id", "username", "display_name", "role", "created_at"}
    assert removed.json() == {"status": "ok"}
    assert member_client.get("/api/me").status_code == 401
    assert stranger(headers={"Authorization": f"Bearer {mac.secret}"}).get("/api/mac/tracking").status_code == 401
    assert (own.status_code, own.json()) == (400, {"detail": "the owner can't be removed"})
    assert unknown.status_code == 404
    assert [account["username"] for account in after] == [AUTH[0].lower()]


def test_five_wrong_passwords_lock_the_username_with_the_same_message():
    with open_client(None) as client:
        misses = [client.post("/api/login", json={"username": AUTH[0], "password": "wrong"}) for _ in range(5)]
        locked = client.post("/api/login", json={"username": AUTH[0], "password": AUTH[1]})
        unknown = client.post("/api/login", json={"username": "nobody", "password": "x"})
    replies = misses + [locked, unknown]
    assert [reply.status_code for reply in replies] == [401] * 7
    assert {reply.text for reply in replies} == {'{"detail":"wrong username or password"}'}
    assert "set-cookie" not in locked.headers and "www-authenticate" not in locked.headers


@pytest.mark.parametrize(
    "lock, copies, skips",
    [
        (MY_LOGIN, [MY_LOGIN], True),
        (MY_LOGIN, [], False),
        (MY_LOGIN, ["someone@example.com"], False),
        (MY_LOGIN, [MY_LOGIN, MY_LOGIN], False),
        ("", [MY_LOGIN], False),  # the variable unset: the header means nothing
    ],
)
def test_a_sign_in_from_my_devices_skips_the_lockout(monkeypatch, caplog, lock, copies, skips):
    monkeypatch.setattr(auth_routes, "TAILSCALE_LOGIN", lock)
    find_owner()
    funnel = stranger()
    for _ in range(5):
        funnel.post("/api/login", json={"username": AUTH[0], "password": "a stranger's guess"})
    mine, headers = stranger(), [(auth_routes.TAILSCALE_HEADER, copy) for copy in copies]
    with caplog.at_level(logging.DEBUG, logger="dayanpi"):
        typos = [mine.post("/api/login", json={"username": AUTH[0], "password": "my typo"}, headers=headers) for _ in range(3)]
        right = mine.post("/api/login", json={"username": AUTH[0], "password": AUTH[1]}, headers=headers)
    still_locked = funnel.post("/api/login", json={"username": AUTH[0], "password": AUTH[1]})
    assert {(typo.status_code, typo.text) for typo in typos} == {(401, '{"detail":"wrong username or password"}')}
    assert right.status_code == (200 if skips else 401)
    assert (COOKIE in right.cookies) is skips
    assert still_locked.status_code == 401, "the internet still waits either way"
    assert caplog.records == [], "nothing new in the journal"


def test_joining_from_an_invite_signs_the_member_in():
    with open_client() as owner:
        made = owner.post("/api/invites", json={}).json()
        listed = owner.get("/api/invites").json()
        newcomer = stranger()
        page = newcomer.get(f"/join/{made['code']}")
        body = {"code": made["code"], "display_name": "  Bo ", "username": " Bo.B ", "password": MEMBER_PASSWORD}
        joined = newcomer.post("/api/join", json=body)
        me = newcomer.get("/api/me")
        reused = stranger().post("/api/join", json={**body, "username": "cy"})
        second = owner.post("/api/invites", json={}).json()["code"]
        taken = stranger().post("/api/join", json={**body, "code": second})
        bad = [
            stranger().post("/api/join", json={**body, "code": second, **change}).status_code
            for change in ({"password": "too short"}, {"username": "x"}, {"display_name": " "}, {"display_name": "a\x00b"})
        ]
        add_member("cy")
        add_member("di")
        full = stranger().post("/api/join", json={**body, "code": second, "username": "ed"})
        no_more = owner.post("/api/invites", json={})
    assert set(made) == {"invite", "code"} and set(made["invite"]) == {"id", "created_at", "expires_at"}
    assert listed == {"invites": [made["invite"]]}
    assert (page.status_code, page.text) == (200, app.INDEX_PAGE.read_text())
    assert joined.status_code == 200 and COOKIE in joined.headers["set-cookie"]
    assert joined.json()["user"] == {"id": joined.json()["user"]["id"], "username": "bo.b", "display_name": "Bo", "role": "member"}
    assert me.json() == joined.json()
    assert (reused.status_code, reused.json()) == (404, {"detail": "this invite doesn't work any more"})
    assert (taken.status_code, taken.json()) == (409, {"detail": "that username is taken"})
    assert bad == [422, 422, 422, 422]
    assert (full.status_code, full.json()) == (403, {"detail": "the room is full"})
    assert (no_more.status_code, no_more.json()) == (403, {"detail": "the room is full"})


def test_your_own_name_and_password():
    member = add_member()
    here = let_in(stranger(), member)
    there = let_in(stranger(), member)
    wrong = here.post("/api/me/password", json={"current_password": "nope", "new_password": "x" * 10})
    short = here.post("/api/me/password", json={"current_password": MEMBER_PASSWORD, "new_password": "x" * 9})
    changed = here.post("/api/me/password", json={"current_password": MEMBER_PASSWORD, "new_password": "a new password!"})
    renamed = here.patch("/api/me", json={"display_name": "  Bo B. "})
    assert (wrong.status_code, wrong.json()) == (400, {"detail": "wrong password"})
    assert short.status_code == 422
    assert changed.json() == {"status": "ok"}
    assert here.get("/api/me").status_code == 200
    assert there.get("/api/me").status_code == 401, "a password change ends the other sessions"
    assert stranger().post("/api/login", json={"username": "bo", "password": "a new password!"}).status_code == 200
    assert renamed.json()["user"]["display_name"] == "Bo B."
    assert here.patch("/api/me", json={"display_name": "x" * 41}).status_code == 422


def test_strangers_missing_at_the_sign_in_cant_stop_a_password_change():
    here = let_in(stranger(), add_member())
    misses = [stranger().post("/api/login", json={"username": "bo", "password": "guess"}).status_code for _ in range(5)]
    changed = here.post("/api/me/password", json={"current_password": MEMBER_PASSWORD, "new_password": "a new password!"})
    assert misses == [401] * 5
    assert changed.json() == {"status": "ok"}, "the right password works while the sign-in waits"


def test_wrong_current_passwords_wait_on_their_own_and_count_toward_the_sign_in():
    here = let_in(stranger(), add_member())
    wrong = [here.post("/api/me/password", json={"current_password": "nope", "new_password": "x" * 10}).status_code for _ in range(5)]
    waiting = here.post("/api/me/password", json={"current_password": MEMBER_PASSWORD, "new_password": "a new password!"})
    sign_in = stranger().post("/api/login", json={"username": "bo", "password": MEMBER_PASSWORD})
    assert wrong == [400] * 5
    assert (waiting.status_code, waiting.json()) == (429, {"detail": "too many tries, wait a bit"})
    assert sign_in.status_code == 401, "the misses started the sign-in's wait too"


def test_a_bad_body_gets_a_422_that_never_repeats_what_was_sent(caplog):
    secret = "MyRealPassw0rd"
    bodies = [
        ("/api/login", '{"username": "tester", "password": "%s\\ud800"}' % secret),
        ("/api/login", '{"username": NaN, "password": "%s"}' % secret),
        ("/api/login", '[NaN, "%s"]' % secret),
        ("/api/login", '{"username": "tester", "password": ["%s"]}' % secret),
        ("/api/join", '{"code": "c", "display_name": "Bo", "username": "bo", "password": Infinity}'),
    ]
    replies = [stranger().post(path, content=body, headers={"Content-Type": "application/json"}) for path, body in bodies]
    assert [reply.status_code for reply in replies] == [422] * len(bodies)
    first = replies[0].json()["detail"][0]
    assert (set(first), first["loc"], first["type"]) == ({"loc", "msg", "type"}, ["body", "password"], "string_unicode")
    assert not any(secret in reply.text or '"input"' in reply.text for reply in replies)
    assert secret not in caplog.text


def test_writes_need_a_json_body():
    with open_client() as client:
        form = client.post("/api/todos", data={"text": "sneaky"})
        plain = client.post("/api/todos", content=b'{"text": "sneaky"}', headers={"Content-Type": "text/plain"})
        bare_delete = client.delete("/api/todos/whatever")
        form_login = stranger().post("/api/login", data={"username": AUTH[0], "password": AUTH[1]})
        form_logout = client.post("/api/logout", data={"x": "1"})
        still_in = client.get("/api/me")
        charset = client.post("/api/todos", content=b'{"text": "json with a charset"}', headers={"Content-Type": "application/json; charset=utf-8"})
        delete(client, f"/api/todos/{charset.json()['item']['id']}")
    assert [reply.status_code for reply in (form, plain, bare_delete, form_login, form_logout)] == [415] * 5
    assert form.json() == {"detail": "send JSON"}
    assert "set-cookie" not in form_login.headers
    assert still_in.status_code == 200, "another site's form can't sign you out either"
    assert charset.status_code == 200


def test_writes_must_say_how_big_they_are_and_stay_small():
    """Checked before anything reads the body, so a stranger can't fill the Pi's memory through the sign-in."""
    client = stranger()
    huge = client.post("/api/login", content=json.dumps({"username": "x", "password": "p" * app.MAX_BODY_BYTES}), headers={"Content-Type": "application/json"})
    chunked = client.post("/api/login", content=iter([b'{"username": "x", ', b'"password": "y"}']), headers={"Content-Type": "application/json"})
    no_length = client.post("/api/login", content=b"{}", headers={"Content-Type": "application/json", "Content-Length": ""})
    small = client.post("/api/login", json={"username": "nobody", "password": "x"})
    assert (huge.status_code, huge.json()) == (413, {"detail": "too big"})
    assert [chunked.status_code, no_length.status_code, small.status_code] == [413, 413, 401]


def test_sign_ins_waiting_for_scrypt_leave_the_shared_threads_to_everything_else():
    owner = find_owner()
    release = threading.Event()
    busy = [auth_routes.scrypt_pool.submit(release.wait) for _ in range(auth_routes.SCRYPT_AT_ONCE)]
    replies = []
    try:
        with TestClient(app.app, base_url=BASE_URL) as client:  # one event loop, so one shared thread pool
            limiter = client.portal.call(anyio.to_thread.current_default_thread_limiter)
            client.portal.call(setattr, limiter, "total_tokens", 1)  # a sign-in holding a shared thread would stall the rest
            let_in(client, owner)
            logins = [threading.Thread(target=client.post, args=("/api/login",), kwargs={"json": {"username": f"nobody{index}", "password": "x"}}) for index in range(3)]
            for login in logins:
                login.start()
            deadline = time.monotonic() + 5
            while auth_routes.scrypt_pool._work_queue.qsize() < len(logins) and time.monotonic() < deadline:
                time.sleep(0.01)
            todos = threading.Thread(target=lambda: replies.append(client.get("/api/todos").status_code))
            todos.start()
            todos.join(5)
            answered_in_time = list(replies)
            release.set()
            for login in logins + [todos]:
                login.join(10)
    finally:
        release.set()
        for job in busy:
            job.result(5)
    assert answered_in_time == [200], "a sync route answers while three sign-ins wait for scrypt"


# (method, route) -> (the path to ask, the JSON body, then the status for no session, a member and the owner).
# Owner writes to the owner's data send bad bodies (a 422 past the door) so nothing changes.
ACCESS = {
    ("POST", "/api/login"): ("/api/login", {"username": "nobody", "password": "nope"}, 401, 401, 401),
    ("POST", "/api/logout"): ("/api/logout", {}, 200, 200, 200),
    ("POST", "/api/join"): ("/api/join", {"code": "nope", "display_name": "Ed", "username": "ed", "password": "x" * 10}, 404, 404, 404),
    ("GET", "/api/me"): ("/api/me", None, 401, 200, 200),
    ("PATCH", "/api/me"): ("/api/me", {"display_name": "Still Me"}, 401, 200, 200),
    ("POST", "/api/me/password"): ("/api/me/password", {"current_password": "wrong", "new_password": "x" * 10}, 401, 400, 400),
    ("GET", "/api/tokens"): ("/api/tokens", None, 401, 200, 200),
    ("POST", "/api/tokens"): ("/api/tokens", {"name": "mac"}, 401, 200, 200),
    ("DELETE", "/api/tokens/{token_id}"): ("/api/tokens/999999", {}, 401, 404, 404),
    ("GET", "/api/invites"): ("/api/invites", None, 401, 403, 200),
    ("POST", "/api/invites"): ("/api/invites", {}, 401, 403, 200),
    ("DELETE", "/api/invites/{invite_id}"): ("/api/invites/999999", {}, 401, 403, 404),
    ("GET", "/api/accounts"): ("/api/accounts", None, 401, 403, 200),
    ("DELETE", "/api/accounts/{account_id}"): ("/api/accounts/999999", {}, 401, 403, 404),
    ("GET", "/api/stats"): ("/api/stats", None, 401, 403, 200),
    ("GET", "/api/health"): ("/api/health", None, 200, 200, 200),
    ("GET", "/api/focus"): ("/api/focus", None, 401, 200, 200),
    ("GET", "/api/days"): ("/api/days?month=1999-01", None, 401, 200, 200),
    ("GET", "/api/apps"): ("/api/apps", None, 401, 200, 200),
    ("GET", "/api/days/{day}"): ("/api/days/1999-01-01", None, 401, 404, 404),
    ("GET", "/api/todos"): ("/api/todos", None, 401, 200, 200),
    ("POST", "/api/todos"): ("/api/todos", {"text": ""}, 401, 403, 422),
    ("PATCH", "/api/todos/{item_id}"): ("/api/todos/nope", {"done": True}, 401, 403, 404),
    ("DELETE", "/api/todos/{item_id}"): ("/api/todos/nope", {}, 401, 403, 404),
    ("POST", "/api/mac/app"): ("/api/mac/app", {"app": ""}, 401, 403, 422),
    ("GET", "/api/mac/tracking"): ("/api/mac/tracking", None, 401, 200, 200),
    ("POST", "/api/mac/tracking"): ("/api/mac/tracking", {"enabled": "maybe"}, 401, 403, 422),
    ("GET", "/api/stream"): ("/api/stream", None, 401, 200, 200),
    ("GET", "/video"): ("/video", None, 401, 404, 200),
    ("GET", "/video/side"): ("/video/side", None, 401, 404, 200),
    ("GET", "/login"): ("/login", None, 200, 200, 200),
    ("GET", "/join/{code}"): ("/join/abc_DEF-123", None, 200, 200, 200),
    ("GET", "/settings"): ("/settings", None, 303, 200, 200),
    ("GET", "/me"): ("/me", None, 303, 200, 200),
    ("GET", "/pi"): ("/pi", None, 303, 200, 200),  # members get the page too; it sends them on to /me
    ("GET", "/"): ("/", None, 303, 200, 200),  # the static mount: the dashboard and its files
}


def test_every_route_has_an_access_rule_and_keeps_it(monkeypatch):
    routes = {(method, route.path or "/") for route in list_routes(app.app.routes) for method in getattr(route, "methods", None) or {"GET"}}
    assert set(ACCESS) == routes, "a new route needs its row in ACCESS"

    async def one_event(request):
        yield b"data: {}\n\n"

    monkeypatch.setattr(app, "event_stream", one_event)
    monkeypatch.setattr(app, "frame_generator", lambda camera, token: iter([b"frame"]))
    monkeypatch.setattr(app, "side_stream", FakeCamera())
    owner = find_owner()
    member = add_member()
    for (method, route), (path, body, *expected) in ACCESS.items():
        got = []
        for user in (None, member, owner):
            client = stranger() if user is None else let_in(stranger(), user)
            got.append(client.request(method, path, json=body, follow_redirects=False).status_code)
        assert got == expected, f"{method} {route}: no session, member, owner"


def test_the_owner_only_reads_turn_a_member_away():
    member = let_in(stranger(), add_member())
    for path in ("/api/stats", "/api/invites", "/api/accounts"):
        reply = member.get(path)
        assert (reply.status_code, reply.json()) == (403, {"detail": "only the owner can do that"}), path


@pytest.mark.parametrize("path", ["/login", "/join/abc_DEF-123", "/settings", "/me", "/pi"])
def test_the_page_routes_serve_the_page(path):
    signed_in = let_in(stranger(), find_owner()).get(path)
    signed_out = stranger().get(path, follow_redirects=False)
    assert (signed_in.status_code, signed_in.text) == (200, app.INDEX_PAGE.read_text())
    if path in ("/settings", "/me", "/pi"):
        assert (signed_out.status_code, signed_out.headers["location"]) == (303, "/login?next=" + quote(path, safe=""))
    else:
        assert (signed_out.status_code, signed_out.text) == (200, app.INDEX_PAGE.read_text())


def test_without_a_session_pages_go_to_the_sign_in_and_the_api_says_401():
    client = stranger()
    page = client.get("/settings?tab=tokens", follow_redirects=False)
    odd_codes = [client.get(path, follow_redirects=False).status_code for path in ("/join/a.b", "/join/" + "a" * 65)]
    api = client.get("/api/focus", follow_redirects=False)
    video = client.get("/video", follow_redirects=False)
    assert (page.status_code, page.headers["location"]) == (303, "/login?next=%2Fsettings%3Ftab%3Dtokens")
    assert odd_codes == [303, 303]
    assert (api.status_code, api.json()) == (401, {"detail": "sign in first"})
    assert video.status_code == 401


def test_only_exact_paths_are_public():
    # httpx tidies "..", so these go straight to the check instead of through a client.
    assert app.is_public("GET", "/assets/index-abc.js") and app.is_public("HEAD", "/login")
    assert app.is_public("POST", "/api/join") and not app.is_public("GET", "/api/join")
    closed = ["/assets/../index.html", "/assets/a/../../api/stats", "/assets\\..\\x", "/login/", "/api/health/x", "/join/a/b", "/join/", "/assetsx/a.js", "/api/login"]
    assert [path for path in closed if app.is_public("GET", path)] == []
    assert not app.is_public("POST", "/api/todos") and not app.is_public("DELETE", "/api/logout")


@pytest.mark.parametrize("path", ["/api/stats", "/video", "/join/abc", "/"])
def test_every_websocket_handshake_is_closed(path):
    # The session middleware never sees these, so nothing past the gate may.
    with pytest.raises(WebSocketDisconnect) as closed:
        let_in(stranger(), find_owner()).websocket_connect(path).__enter__()
    assert closed.value.code == 1008


def test_a_mac_token_only_opens_the_mac_routes(fresh_mac_tracking):
    with open_client() as owner:
        made = owner.post("/api/tokens", json={"name": "  MacBook "}).json()
        listed = owner.get("/api/tokens").json()
        mac = stranger(headers={"Authorization": f"Bearer {made['secret']}"})
        report = mac.post("/api/mac/app", json={"app": "Code"})
        switch = mac.get("/api/mac/tracking")
        elsewhere = [mac.get(path, follow_redirects=False).status_code for path in ("/api/todos", "/api/focus", "/api/me", "/video", "/api/stream", "/", "/settings")]
        with_cookie = let_in(stranger(headers={"Authorization": f"Bearer {made['secret']}"}), find_owner()).get("/api/focus")
        wrong_token = let_in(stranger(headers={"Authorization": "Bearer dpi_wrong"}), find_owner()).get("/api/mac/tracking")
        used = owner.get("/api/tokens").json()["tokens"][0]
        revoked = delete(owner, f"/api/tokens/{made['token']['id']}")
        after = mac.get("/api/mac/tracking")
        none_left = owner.get("/api/tokens").json()
    assert made["secret"].startswith("dpi_") and made["token"]["name"] == "MacBook"
    assert set(made["token"]) == {"id", "name", "created_at", "last_used_at"}
    assert listed == {"tokens": [made["token"]]}, "listed without the secret"
    assert report.status_code == 200 and switch.json() == {"enabled": True}
    assert elsewhere == [401] * 7
    assert with_cookie.status_code == 401, "a Bearer header outside /api/mac/ is refused, cookie or not"
    assert wrong_token.status_code == 401, "on /api/mac/ the token counts and the cookie is ignored"
    assert used["last_used_at"] is not None
    assert revoked.json() == {"status": "ok"}
    assert after.status_code == 401
    assert none_left == {"tokens": []}


def test_a_members_token_is_read_only_and_their_own(fresh_mac_tracking):
    owner_token = auth_routes.accounts.create_token(find_owner().id, "laptop", time.time())
    member = let_in(stranger(), add_member())
    made = member.post("/api/tokens", json={"name": "mac"}).json()
    mac = stranger(headers={"Authorization": f"Bearer {made['secret']}"})
    assert mac.post("/api/mac/app", json={"app": "Code"}).status_code == 403
    assert mac.post("/api/mac/tracking", json={"enabled": False}).status_code == 403
    assert mac.get("/api/mac/tracking").json() == {"enabled": True}
    assert delete(member, f"/api/tokens/{owner_token.token.id}").status_code == 404
    assert [token["id"] for token in member.get("/api/tokens").json()["tokens"]] == [made["token"]["id"]]
    assert auth_routes.accounts.find_token_user(owner_token.secret, time.time()) is not None


@pytest.mark.parametrize(
    "role, header, expected",
    [
        ("owner", MY_LOGIN, 200),
        ("owner", None, 404),
        ("owner", "someone@example.com", 404),
        ("owner", MY_LOGIN.upper(), 404),
        ("member", MY_LOGIN, 404),
    ],
)
def test_the_camera_only_answers_the_owner_on_their_own_devices(monkeypatch, role, header, expected):
    monkeypatch.setattr(auth_routes, "TAILSCALE_LOGIN", MY_LOGIN)
    monkeypatch.setattr(app, "side_stream", FakeCamera())
    monkeypatch.setattr(app, "frame_generator", lambda camera, token: iter([b"frame"]))
    headers = {} if header is None else {auth_routes.TAILSCALE_HEADER: header}
    client = let_in(stranger(headers=headers), find_owner() if role == "owner" else add_member())
    feeds = [client.get(path) for path in ("/video", "/video/side")]
    access = client.get("/api/focus").json()["camera_access"]
    assert [feed.status_code for feed in feeds] == [expected, expected]
    if expected == 404:
        assert all(feed.json() == {"detail": "Not Found"} for feed in feeds), "the same 404 as a route that isn't there"
    assert access == ("open" if expected == 200 else "owner_only" if role == "member" else "tailscale_only")


def test_a_second_copy_of_the_tailscale_header_does_not_count(monkeypatch):
    monkeypatch.setattr(auth_routes, "TAILSCALE_LOGIN", MY_LOGIN)
    monkeypatch.setattr(app, "frame_generator", lambda camera, token: iter([b"frame"]))
    client = let_in(stranger(), find_owner())
    reply = client.get("/video", headers=[(auth_routes.TAILSCALE_HEADER, MY_LOGIN), (auth_routes.TAILSCALE_HEADER, "someone@example.com")])
    assert reply.status_code == 404


def test_without_the_lock_the_owner_gets_the_camera_like_before(monkeypatch, caplog):
    monkeypatch.setattr(app, "side_stream", FakeCamera())
    monkeypatch.setattr(app, "frame_generator", lambda camera, token: iter([b"frame"]))
    with caplog.at_level(logging.INFO):
        with open_client() as client:
            feeds = [client.get(path).status_code for path in ("/video", "/video/side")]
            access = client.get("/api/focus").json()["camera_access"]
    member = let_in(stranger(headers={auth_routes.TAILSCALE_HEADER: MY_LOGIN}), add_member())
    assert feeds == [200, 200] and access == "open"
    assert member.get("/video").status_code == 404 and member.get("/api/focus").json()["camera_access"] == "owner_only"
    lines = [record for record in caplog.records if "Tailscale" in record.getMessage()]
    assert [(record.levelno, record.getMessage()) for record in lines] == [(logging.WARNING, "camera not locked to Tailscale, don't turn on Funnel")]


def test_with_the_lock_startup_says_so_once(monkeypatch, caplog):
    monkeypatch.setattr(auth_routes, "TAILSCALE_LOGIN", MY_LOGIN)
    with caplog.at_level(logging.INFO):
        with TestClient(app.app):
            pass
    lines = [record for record in caplog.records if "Tailscale" in record.getMessage()]
    assert [(record.levelno, record.getMessage()) for record in lines] == [(logging.INFO, f"camera locked to Tailscale login {MY_LOGIN}")]


def test_the_boxes_only_go_where_the_feed_does(monkeypatch):
    class FakeScanner:
        def scan(self, image):
            raise AssertionError("no frames here")

    monkeypatch.setattr(focus_worker, "build_scanner", lambda: FakeScanner())
    monkeypatch.setattr(auth_routes, "TAILSCALE_LOGIN", MY_LOGIN)
    overlay = {"at": time.time(), "frame_width": 640, "frame_height": 480, "boxes": [{"kind": "phone", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}]}
    with open_client(headers={auth_routes.TAILSCALE_HEADER: MY_LOGIN}) as client:
        app.worker.last_overlay = overlay
        app.worker.last_side_overlay = overlay
        mine = client.get("/api/focus").json()
        away = let_in(stranger(), find_owner()).get("/api/focus").json()
        member = let_in(stranger(headers={auth_routes.TAILSCALE_HEADER: MY_LOGIN}), add_member()).get("/api/focus").json()
    assert mine["camera_access"] == "open" and mine["overlay"]["boxes"] and mine["side_overlay"]["boxes"]
    assert (away["camera_access"], away["overlay"], away["side_overlay"]) == ("tailscale_only", None, None)
    assert (member["camera_access"], member["overlay"], member["side_overlay"]) == ("owner_only", None, None)


def test_the_access_log_never_shows_an_invite_code():
    seen = []

    class KeepHandler(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    access = logging.getLogger("uvicorn.access")
    handler = KeepHandler()
    level, disabled = access.level, access.disabled
    access.addHandler(handler)
    access.setLevel(logging.INFO)
    access.disabled = False
    try:
        # uvicorn's own access line: client, method, path with query, HTTP version, status.
        # A stray "/" on a pasted link misses the join page, so the sign-in redirect carries the code in its query.
        redirect = stranger().get("/join/SECRETcode-123/", follow_redirects=False).headers["location"]
        for path in ("/join/SECRETcode-123", "/join/SECRETcode-123/", redirect, "/login?next=/join/SECRETcode-123&x=1", "/api/focus"):
            access.info('%s - "%s %s HTTP/%s" %d', "100.64.0.1:51000", "GET", path, "1.1", 200)
    finally:
        access.removeHandler(handler)
        access.setLevel(level)
        access.disabled = disabled
    assert redirect == "/login?next=%2Fjoin%2FSECRETcode-123%2F"
    assert [line.split('"')[1] for line in seen] == [
        "GET /join/… HTTP/1.1",
        "GET /join/… HTTP/1.1",
        "GET /login?next=%2Fjoin%2F… HTTP/1.1",
        "GET /login?next=/join/…&x=1 HTTP/1.1",
        "GET /api/focus HTTP/1.1",
    ]
    assert not any("SECRET" in line for line in seen)
