import gc
import json
import logging
import math
import os
import re
import subprocess
import tempfile
import threading
import time
from collections import defaultdict
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
from dayanpi.focus.camera_source import CAMERA_SOURCE_FILE, CameraSourceSetting  # noqa: E402
from dayanpi.focus.desks import Desks  # noqa: E402
from dayanpi.focus.pictures import PICTURE_MAX_BASE64, PICTURE_MAX_BYTES  # noqa: E402
from dayanpi.focus.sharing import DEFAULT_SHARING  # noqa: E402
from dayanpi.focus.tracker import format_day  # noqa: E402
from dayanpi.paths import MODELS_DIR  # noqa: E402
from dayanpi.utils.limits import NOTE_EVERY_S, RefusalNote, TokenBucket  # noqa: E402

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
    # The limits are in memory and ids start over with each accounts.db, so every test gets them full.
    monkeypatch.setattr(app, "write_allowances", defaultdict(app.make_write_allowance))
    monkeypatch.setattr(app, "write_refusals", RefusalNote())
    monkeypatch.setattr(auth_routes, "stranger_sign_ins", TokenBucket(auth_routes.STRANGER_SIGN_INS_PER_S, auth_routes.STRANGER_SIGN_IN_BURST))
    monkeypatch.setattr(auth_routes, "stranger_refusals", RefusalNote())


@pytest.fixture(autouse=True)
def fresh_desks(monkeypatch, tmp_path):
    """Every test's own data folder for the desks (tmp_path/users), and no owner's desk until a startup or use_owner_desk()."""
    monkeypatch.setattr(app, "desks", Desks(tmp_path))
    monkeypatch.setattr(app, "owner_desk", None)
    monkeypatch.setattr(app, "llm", None)
    monkeypatch.setattr(app, "coach_writer", None)
    monkeypatch.setattr(app, "latest_focus", {})
    monkeypatch.setattr(app, "latest_snapshot", None)
    monkeypatch.setattr(app, "latest_room", None)


def desk_of(user):
    desk = app.desks.open(user.username, time.time())
    return desk


def use_owner_desk(monkeypatch):
    """For a test that drives the camera's hooks without a startup: the owner's desk, as the startup would set it."""
    desk = desk_of(find_owner())
    monkeypatch.setattr(app, "owner_desk", desk)
    return desk


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


def make_session_hash(user):
    """A token is made through a session of its user's, still there when it's made."""
    session_hash = auth_routes.accounts.find_session(auth_routes.accounts.create_session(user.id, time.time()), time.time()).token_hash
    return session_hash


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
        assert {path.rsplit(".", 1)[-1] for path in linked} == {"js", "css", "svg", "png"}  # svg and png: the tab icon
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


def test_every_tab_icon_loads_without_a_session():
    """The page swaps the SVG for your state's (hooks/useTabIcon), and the sign-in page shows the gray one."""
    types = {"svg": "image/svg+xml", "png": "image/png"}
    for name in ("icon-working.svg", "icon-phone.svg", "icon-away.svg", "icon-unknown.svg", "icon-32.png", "apple-touch-icon.png"):
        response = stranger().get(f"/assets/{name}")
        assert (response.status_code, response.headers["content-type"].split(";")[0]) == (200, types[name.rsplit(".", 1)[-1]]), name


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


def test_the_mac_app_route_takes_a_site_or_none_and_logs_it():
    from dayanpi.focus.tracker import format_day

    log = desk_of(find_owner()).log
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

    desk = use_owner_desk(monkeypatch)
    said = []
    monkeypatch.setattr(app.voice, "say", lambda text: said.append(text) or True)
    update = focus.FocusUpdate(
        state="phone",
        callouts=[focus.Callout("instant_pickup", "Already?"), focus.Callout("quiet", "Only for the log.", speak=False)],
    )
    app.handle_focus_update(desk, update, time.time())
    assert said == ["Already?"]


def test_every_hand_sign_does_something():
    from dayanpi.vision.gestures import HAND_SIGNS

    assert set(HAND_SIGNS) == set(app.SIGN_ACTIONS)


def test_peace_speaks_the_coachs_message_and_logs_which_kind(monkeypatch, tmp_path):
    from dayanpi.focus.tracker import format_day

    said = []
    desk = use_owner_desk(monkeypatch)
    log, todos = desk.log, desk.todos
    monkeypatch.setattr(app.voice, "say", lambda text: said.append(text) or True)
    now = time.time()
    todos.add("finish the report", now)
    laundry = todos.add("do laundry", now)["id"]
    todos.add("reply to emails", now)
    todos.change(laundry, now, done=True)

    app.handle_gesture(desk, "peace", now)

    assert len(said) == 1
    assert "You have 2 things to do: finish the report and reply to emails. Done today: do laundry." in said[0]
    gestures = [line for line in log.read_day(format_day(now)) if line["event"] == "gesture"]
    assert [(line["name"], line["spoken"]) for line in gestures] == [("peace", "template")]


class FakeAplay:
    """subprocess.run for run_speech_job: Piper answers at once, and aplay plays until it's released."""

    def __init__(self):
        self.playing = threading.Event()
        self.release = threading.Event()

    def __call__(self, command, **options):
        if command[0] == "aplay":
            self.playing.set()
            self.release.wait(timeout=5)
        return subprocess.CompletedProcess(command, 0, stdout=b"audio", stderr=b"")


def test_the_status_says_what_the_peace_sign_is_saying_until_aplay_finishes(monkeypatch, tmp_path):
    from dayanpi.hardware.voice import VoiceAnnouncer, VoiceSettings, run_speech_job

    model = tmp_path / "voice.onnx"
    model.write_bytes(b"not a real model")
    model.with_name("voice.onnx.json").write_text('{"audio": {"sample_rate": 22050}}')
    aplay = FakeAplay()
    speaker = VoiceAnnouncer(
        VoiceSettings(backend="piper", piper_model=model, audio_device=None),
        runner=lambda job: run_speech_job(job, run=aplay),
        find_program=lambda name: f"/usr/bin/{name}",
        piper_installed=lambda: True,
    )
    monkeypatch.setattr(app, "voice", speaker)
    with open_client() as client:
        assert client.get("/api/focus").json()["spoken"] is None
        app.handle_gesture(app.owner_desk, "peace", time.time())
        assert aplay.playing.wait(timeout=5)
        playing = client.get("/api/focus").json()["spoken"]
        aplay.release.set()
        deadline = time.monotonic() + 5
        while speaker.is_saying(playing["text"]) and time.monotonic() < deadline:
            time.sleep(0.01)
        finished = client.get("/api/focus").json()["spoken"]
    assert playing["text"].startswith("It's ") and playing["speaking"] is True
    assert 0 <= playing["age_s"] < 5
    assert (finished["text"], finished["at"], finished["speaking"]) == (playing["text"], playing["at"], False)


def test_the_spoken_text_is_never_logged(monkeypatch, caplog):
    from dayanpi.focus.tracker import format_day

    desk = use_owner_desk(monkeypatch)
    log = desk.log
    desk.todos.add("call the dentist", time.time())
    now = time.time()
    assert app.voice.enabled is False, "the real voice, off: it used to log what it would have said"
    with caplog.at_level(logging.INFO):
        app.handle_gesture(desk, "peace", now)
        text = desk.last_spoken["text"]
        app.speak_to(desk, app.nudge_line("Sam"), now, kind="nudge")
    assert "call the dentist" in text
    assert "would say" in caplog.text
    for said in (text, "call the dentist", app.nudge_line("Sam")):
        assert said not in caplog.text
    assert text not in json.dumps(log.read_day(format_day(now)))


def test_the_coach_only_writes_ahead_with_a_model_set():
    with TestClient(app.app):
        assert app.llm is None, "DAYANPI_LLM_MODEL isn't set in the tests"
        assert app.coach_writer is None


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


def test_a_full_to_do_list_is_a_409(monkeypatch):
    monkeypatch.setattr("dayanpi.focus.todos.TODOS_MAX", 2)
    client = let_in(stranger(), add_member())
    added = [client.post("/api/todos", json={"text": f"item {index}"}).status_code for index in range(3)]
    assert added == [200, 200, 409]
    assert len(client.get("/api/todos").json()["open"]) == 2


def test_working_counts_time_for_the_current_todo(monkeypatch):
    from dayanpi.focus.tracker import FocusUpdate

    desk = use_owner_desk(monkeypatch)
    todos = desk.todos
    now = time.time()
    item_id = todos.add("hook test", now)["id"]
    todos.change(item_id, now, current=True)
    for second in range(4):
        app.handle_focus_update(desk, FocusUpdate(state="working"), now + second)
    for second in range(4, 8):
        app.handle_focus_update(desk, FocusUpdate(state="phone"), now + second)
    open_items = todos.snapshot(now + 8)["open"]
    assert [item["seconds"] for item in open_items if item["id"] == item_id] == [4]


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

    def frame_age_s(self) -> float | None:
        return None


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

    def frame_age_s(self) -> float:
        return 0.01


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


def test_the_stream_sends_each_viewer_their_own_desk_and_the_pi_only_to_the_owner(real_server, monkeypatch):
    box = {"kind": "phone", "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
    member, owner = add_member(), find_owner()
    snapshot = {"temp_c": 51.0, "throttled": {"under_voltage": False}}
    mine = {"state": "working", "todos": {"open": ["mine"]}, "overlay": {"boxes": [box]}, "side_overlay": None}
    theirs = {"state": "unknown", "todos": {"open": ["theirs"]}, "overlay": None, "side_overlay": None}
    monkeypatch.setattr(app, "latest_snapshot", snapshot)
    monkeypatch.setattr(app, "latest_focus", {owner.username: mine, member.username: theirs})
    with httpx.stream("GET", real_server + "/api/stream", headers=session_header(member), timeout=3) as response:
        [member_event] = read_events(response, 1)
    with httpx.stream("GET", real_server + "/api/stream", headers=session_header(owner), timeout=3) as response:
        [owner_event] = read_events(response, 1)
    assert member_event == {"focus": {**theirs, "camera_access": "owner_only"}, "room": None}
    assert owner_event == {**snapshot, "focus": {**mine, "camera_access": "open"}, "room": None}
    assert "camera_access" not in app.latest_focus[owner.username], "each viewer's copy, never the shared status"


def make_room(monkeypatch, now: float) -> dict:
    """What snapshot_producer makes each second, from every open desk, for the streams to send."""
    statuses = {desk.username: app.build_desk_status(desk, now) for desk in app.desks.list()}
    room = app.build_room(statuses, now)
    monkeypatch.setattr(app, "latest_snapshot", {"fake": True})
    monkeypatch.setattr(app, "latest_focus", statuses)
    monkeypatch.setattr(app, "latest_room", room)
    return room


def read_member_views(real_server, member, now: float) -> list[str]:
    """Everything a member can read: a stream event and every route they may GET."""
    with httpx.stream("GET", real_server + "/api/stream", headers=session_header(member), timeout=3) as response:
        views = [json.dumps(read_events(response, 1)[0])]
    client = let_in(stranger(), member)
    paths = [path for (method, _), (path, _, _, member_status, _) in ACCESS.items() if method == "GET" and member_status == 200]
    paths += [f"/api/days/{format_day(now)}", f"/api/days?month={format_day(now)[:7]}", "/api/apps?range=week"]
    views += [client.get(path).text for path in paths if not path.startswith(("/api/stream", "/video", "/api/models"))]
    return views


def test_a_hidden_part_is_in_no_stream_and_no_route(real_server, monkeypatch):
    owner, member = find_owner(), add_member()
    desk = desk_of(owner)
    desk_of(member)
    now = time.time()
    plan = desk.todos.add("secret plan", now)
    desk.todos.change(plan["id"], now, current=True)
    desk.tracker.record_app("SecretApp", now, site="secret.example")
    desk.sharing.update({"focus": False, "todos": False, "sites": True})  # sites without apps counts for nothing
    room = make_room(monkeypatch, now)
    seen = "\n".join(read_member_views(real_server, member, now))
    for secret in ("secret plan", "SecretApp", "secret.example"):
        assert secret not in seen
    [mine] = [seat for seat in room["seats"] if seat["username"] == owner.username]
    assert set(mine) == {"username", "name", "here", "state", "seconds_in_state", "shares", "hidden", "nudge"}

    desk.sharing.update({"focus": True, "todos": True, "apps": True})
    make_room(monkeypatch, now)
    seen = "\n".join(read_member_views(real_server, member, now))
    for secret in ("secret plan", "SecretApp", "secret.example", "focus_seconds"):
        assert secret in seen, "switched on, it does reach the room"


def test_an_open_stream_puts_you_in_the_room(real_server, monkeypatch):
    member = add_member()
    desk_of(member)
    now = time.time()
    room = make_room(monkeypatch, now)
    assert [(seat["username"], seat["here"], seat["state"]) for seat in room["seats"]] == [("bo", False, "offline")]
    with httpx.stream("GET", real_server + "/api/stream", headers=session_header(member), timeout=3) as response:
        [event] = read_events(response, 1)
    assert event["room"] == room
    assert time.time() - desk_of(member).seen_at < 5
    [seat] = make_room(monkeypatch, time.time())["seats"]
    assert (seat["here"], seat["state"]) == (True, "unknown")


def test_the_sharing_route_saves_your_switches_and_your_seat_is_what_the_room_gets(monkeypatch):
    owner, member = find_owner(), add_member()
    desk_of(owner)
    client = let_in(stranger(), member)
    reply = client.post("/api/sharing", json={"apps": True, "todos": False})
    assert reply.status_code == 200
    assert reply.json()["sharing"] == DEFAULT_SHARING | {"apps": True, "todos": False}
    assert client.get("/api/focus").json()["sharing"] == reply.json()["sharing"]
    room = make_room(monkeypatch, time.time())
    assert [seat["username"] for seat in room["seats"]] == [owner.username, member.username]
    without_timer = lambda seat: {key: value for key, value in seat.items() if key != "seconds_in_state"}  # noqa: E731
    assert without_timer(reply.json()["seat"]) == without_timer(room["seats"][1]), "Settings' preview is what the room gets"
    assert set(reply.json()["seat"]) == {"username", "name", "here", "state", "seconds_in_state", "shares", "hidden", "focus_seconds", "app", "nudge"}
    for bad in ({"status": False}, {"apps": "yes"}):
        assert client.post("/api/sharing", json=bad).status_code == 422


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


def test_day_routes_serve_past_pages_and_build_today_live():
    from dayanpi.focus.tracker import format_day

    desk = desk_of(find_owner())
    log, days_dir = desk.log, desk.days_dir
    now = time.time()
    today = format_day(now)
    month = today[:7]
    past = f"{month}-01" if today != f"{month}-01" else f"{month}-02"
    days_dir.mkdir(parents=True)
    (days_dir / f"{past}.md").write_text("---\nfocus_minutes: 95\n---\n\n# A past day\n")
    (days_dir / "notes.md").write_text("not a day")
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
    assert page == {"day": past, "today": False, "markdown": "---\nfocus_minutes: 95\n---\n\n# A past day\n", "others": []}
    assert live["today"] is True and "- Focus: 10m" in live["markdown"]
    assert not (days_dir / f"{today}.md").exists(), "today's page is never saved"
    assert missing.status_code == 404
    assert all(code in (404, 422) for code in bad_names)
    assert bad_names[:3] == [422, 422, 422]
    assert bad_month.status_code == 422


@pytest.fixture
def fresh_mac_tracking():
    """The owner's desk's focus log; every test has its own desks, so one switching it off can't leak into the next."""
    log = desk_of(find_owner()).log
    return log


def test_the_mac_tracking_switch_routes(fresh_mac_tracking):
    with open_client() as client:
        assert stranger().get("/api/mac/tracking").status_code == 401
        assert stranger().post("/api/mac/tracking", json={"enabled": False}).status_code == 401
        assert client.get("/api/mac/tracking").json() == {"enabled": True}
        assert client.post("/api/mac/tracking", json={"enabled": False}).json() == {"enabled": False}
        assert client.get("/api/mac/tracking").json() == {"enabled": False}
        assert client.get("/api/focus").json()["mac_tracking"] is False
        bad = [client.post("/api/mac/tracking", json=body).status_code for body in ({}, {"enabled": "no"}, {"enabled": 1}, {"enabled": None})]
    assert bad == [422, 422, 422, 422]
    assert json.loads((desk_of(find_owner()).folder / "mac_tracking.json").read_text()) == {"enabled": False}


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


def test_starting_up_switched_off_logs_that_it_is_paused():
    from dayanpi.focus.mac_tracking import MacTrackingSetting
    from dayanpi.focus.tracker import format_day

    MacTrackingSetting(app.desks.find_folder(find_owner().username) / "mac_tracking.json").set(False)
    with TestClient(app.app):
        pass
    lines = [line for line in desk_of(find_owner()).log.read_day(format_day(time.time())) if line["event"] == "mac_tracking"]
    assert [line["enabled"] for line in lines] == [False]


def write_app_samples(log, day: str, ts: float, app_name: str, count: int, site=None, state="working") -> None:
    for index in range(count):
        log.write({"ts": ts + index, "day": day, "event": "sample", "state": state, "app": app_name, "site": site})


def test_apps_route_ranks_the_top_eight_and_sums_the_rest():
    from dayanpi.focus.tracker import format_day

    log = desk_of(find_owner()).log
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


def test_apps_route_week_sums_seven_days_and_ignores_the_eighth():
    from datetime import datetime, timedelta

    log = desk_of(find_owner()).log
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


def test_apps_route_on_an_empty_day_has_no_apps():
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
        mac = auth_routes.accounts.create_token(make_session_hash(member), "mac", time.time())
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


def test_five_wrong_passwords_lock_the_username_and_say_how_long(monkeypatch):
    monkeypatch.setattr(auth_routes, "stranger_sign_ins", TokenBucket(1000.0, 1000.0))  # this one's about the per-name wait
    with open_client(None) as client:
        misses = [client.post("/api/login", json={"username": AUTH[0], "password": "wrong"}) for _ in range(5)]
        locked = client.post("/api/login", json={"username": AUTH[0], "password": AUTH[1]})
        unknown = [client.post("/api/login", json={"username": "nobody", "password": "x"}) for _ in range(5)]
    assert [reply.status_code for reply in misses[:4]] == [401] * 4
    assert {reply.text for reply in misses[:4]} == {'{"detail":"wrong username or password"}'}
    # The 5th miss starts the 30 s wait, and a try during it isn't checked, right password or not.
    assert [(reply.status_code, reply.json(), reply.headers["retry-after"]) for reply in (misses[4], locked)] == [(429, {"detail": "too many tries, wait a bit"}, "30")] * 2
    assert "set-cookie" not in locked.headers and "www-authenticate" not in locked.headers
    assert [reply.status_code for reply in unknown] == [401] * 4 + [429], "a name that doesn't exist waits the same way"


def test_strangers_get_ten_sign_ins_at_once_then_the_same_wait_for_any_name(monkeypatch, caplog):
    monkeypatch.setattr(auth_routes, "stranger_sign_ins", TokenBucket(0.001, auth_routes.STRANGER_SIGN_IN_BURST))  # no refill
    checked = []
    monkeypatch.setattr(auth_routes, "check_sign_in", lambda store, lockout, username, *rest: checked.append(username))
    find_owner()
    client = stranger()
    with caplog.at_level(logging.WARNING, logger="dayanpi.auth.routes"):
        burst = [client.post("/api/login", json={"username": f"guess{index}", "password": "x"}).status_code for index in range(10)]
        real = client.post("/api/login", json={"username": AUTH[0], "password": AUTH[1]})
        made_up = client.post("/api/login", json={"username": "nobody", "password": "x"})
    assert burst == [401] * 10
    assert len(checked) == 10, "turned away before the scrypt"
    assert (real.status_code, real.json(), real.headers["retry-after"]) == (429, {"detail": "too many tries, wait a bit"}, "1")
    same = [{key: value for key, value in reply.headers.items() if key != "date"} for reply in (real, made_up)]
    assert (real.text, same[0]) == (made_up.text, same[1]), "a real name and a made-up one read the same"
    lines = [record.getMessage() for record in caplog.records if "strangers' sign-ins" in record.getMessage()]
    assert lines == ["turned away 1 strangers' sign-ins in the last minute"], "a line a minute, not one per try"


def test_my_devices_skip_the_strangers_cap_and_never_queue_behind_their_scrypts(monkeypatch):
    monkeypatch.setattr(auth_routes, "TAILSCALE_LOGIN", MY_LOGIN)
    monkeypatch.setattr(auth_routes, "stranger_sign_ins", TokenBucket(0.001, 0.0))  # strangers have nothing left
    find_owner()
    release = threading.Event()
    busy = [auth_routes.scrypt_pool.submit(release.wait) for _ in range(auth_routes.SCRYPT_AT_ONCE)]  # strangers' scrypts fill the shared pool
    replies = []
    try:
        mine = threading.Thread(
            target=lambda: replies.append(
                stranger().post("/api/login", json={"username": AUTH[0], "password": AUTH[1]}, headers={auth_routes.TAILSCALE_HEADER: MY_LOGIN})
            )
        )
        mine.start()
        mine.join(10)
        answered = [reply.status_code for reply in replies]
        funnel = stranger().post("/api/login", json={"username": AUTH[0], "password": AUTH[1]})
    finally:
        release.set()
        for job in busy:
            job.result(5)
    assert answered == [200], "my sign-in ran on its own thread while both shared ones were busy"
    assert funnel.status_code == 429, "the same sign-in without my device is a stranger's"


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
    assert {typo.status_code for typo in typos} == {401 if skips else 429}
    assert right.status_code == (200 if skips else 429)
    assert (COOKIE in right.cookies) is skips
    assert still_locked.status_code == 429, "the internet still waits either way"
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
    assert misses == [401] * 4 + [429]
    assert changed.json() == {"status": "ok"}, "the right password works while the sign-in waits"


def test_wrong_current_passwords_wait_on_their_own_and_count_toward_the_sign_in():
    here = let_in(stranger(), add_member())
    wrong = [here.post("/api/me/password", json={"current_password": "nope", "new_password": "x" * 10}).status_code for _ in range(5)]
    waiting = here.post("/api/me/password", json={"current_password": MEMBER_PASSWORD, "new_password": "a new password!"})
    sign_in = stranger().post("/api/login", json={"username": "bo", "password": MEMBER_PASSWORD})
    assert wrong == [400] * 5
    assert (waiting.status_code, waiting.json()) == (429, {"detail": "too many tries, wait a bit"})
    assert sign_in.status_code == 429, "the misses started the sign-in's wait too"


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


def test_twenty_writes_go_through_at_once_then_it_says_slow_down_and_the_journal_hears_once(monkeypatch, caplog):
    monkeypatch.setattr(app, "WRITES_PER_S", 0.001)  # no refill while this runs; the refill has its own test below
    owner = let_in(stranger(), find_owner())
    bo, sam = let_in(stranger(), add_member("bo")), let_in(stranger(), add_member("sam"))

    def write(client):
        return client.post("/api/mac/tracking", json={"enabled": True})

    with caplog.at_level(logging.WARNING, logger="dayanpi.app"):
        reads = [bo.get("/api/mac/tracking").status_code for _ in range(30)]
        burst = [write(bo).status_code for _ in range(int(app.WRITE_BURST))]
        over = [write(bo) for _ in range(5)]
        others = [write(sam).status_code] + [write(owner).status_code for _ in range(int(app.WRITE_BURST))]
        mine_over = write(owner)
    assert reads == [200] * 30, "reads never count"
    assert burst == [200] * 20
    assert [(reply.status_code, reply.json()) for reply in over] == [(429, {"detail": "slow down"})] * 5
    assert all(int(reply.headers["retry-after"]) >= 1 for reply in over)
    assert others == [200] * 21, "bo's limit is bo's alone"
    assert mine_over.status_code == 429, "mine too"
    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("write limit hit")]
    assert lines == ["write limit hit for bo", f"write limit hit for {find_owner().username}"], "one line, not one per request"


def test_the_allowance_refills_and_its_journal_line_comes_once_a_minute():
    bucket = TokenBucket(app.WRITES_PER_S, app.WRITE_BURST)
    assert [bucket.take(1000.0) for _ in range(20)] == [0.0] * 20
    wait = bucket.take(1000.0)
    assert 0 < wait <= 0.2 and math.ceil(wait) == 1, "Retry-After: 1 at 5 a second"
    assert bucket.take(1000.0 + wait) == 0.0, "one back after its fifth of a second"
    assert bucket.take(1000.0 + wait) > 0
    assert [bucket.take(1100.0) for _ in range(21)].count(0.0) == 20, "back to the whole burst, and no more"
    note = RefusalNote()
    assert [note.count("bo", 1000.0 + offset) for offset in (0, 1, 30, 59)] == [1, 0, 0, 0]
    assert note.count("sam", 1001.0) == 1, "each account its own line"
    assert note.count("bo", 1000.0 + NOTE_EVERY_S) == 4, "then once a minute, saying how many since"


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
    ("POST", "/api/todos"): ("/api/todos", {"text": ""}, 401, 422, 422),  # a member's own desk now
    ("PATCH", "/api/todos/{item_id}"): ("/api/todos/nope", {"done": True}, 401, 404, 404),
    ("DELETE", "/api/todos/{item_id}"): ("/api/todos/nope", {}, 401, 404, 404),
    ("POST", "/api/mac/app"): ("/api/mac/app", {"app": ""}, 401, 422, 422),
    ("GET", "/api/mac/tracking"): ("/api/mac/tracking", None, 401, 200, 200),
    ("POST", "/api/mac/tracking"): ("/api/mac/tracking", {"enabled": "maybe"}, 401, 422, 422),
    ("POST", "/api/track/reading"): ("/api/track/reading", {"person": 2, "phone": 0, "elapsed_ms": 1}, 401, 422, 422),
    ("POST", "/api/track/pause"): ("/api/track/pause", {}, 401, 200, 200),  # no startup here, so my desk is on a browser too
    ("POST", "/api/track/source"): ("/api/track/source", {"source": "webcam"}, 401, 422, 422),
    ("POST", "/api/track/picture"): ("/api/track/picture", {"picture": 5}, 401, 403, 422),  # owner only
    ("POST", "/api/voice"): ("/api/voice", {"bedtime": "25:00"}, 401, 422, 422),
    ("POST", "/api/voice/test"): ("/api/voice/test", {}, 401, 200, 200),
    ("POST", "/api/sharing"): ("/api/sharing", {"focus": "maybe"}, 401, 422, 422),
    ("GET", "/api/people/{username}"): (f"/api/people/{AUTH[0]}", None, 401, 200, 200),  # the owner's desk, only what it shares
    ("GET", "/api/people/{username}/picture"): (f"/api/people/{AUTH[0]}/picture", None, 401, 404, 404),  # video starts off
    ("POST", "/api/nudge"): ("/api/nudge", {"username": ""}, 401, 422, 422),
    ("POST", "/api/room/hide"): ("/api/room/hide", {"username": ""}, 401, 422, 422),
    ("POST", "/api/room/show"): ("/api/room/show", {"username": ""}, 401, 422, 422),
    ("GET", "/people/{username}"): ("/people/sam", None, 303, 200, 200),  # the voice is off in the tests, so nothing plays
    ("GET", "/api/voice/clip"): ("/api/voice/clip", None, 401, 404, 404),
    ("GET", "/api/stream"): ("/api/stream", None, 401, 200, 200),
    ("GET", "/video"): ("/video", None, 401, 404, 200),
    ("GET", "/video/side"): ("/video/side", None, 401, 404, 200),
    ("GET", "/login"): ("/login", None, 200, 200, 200),
    ("GET", "/join/{code}"): ("/join/abc_DEF-123", None, 200, 200, 200),
    ("GET", "/settings"): ("/settings", None, 303, 200, 200),
    ("GET", "/me"): ("/me", None, 303, 200, 200),
    ("GET", "/pi"): ("/pi", None, 303, 200, 200),  # members get the page too; it sends them on to /me
    ("GET", "/track"): ("/track", None, 303, 200, 200),
    ("GET", "/track/test"): ("/track/test", None, 303, 200, 200),
    ("GET", "/sign"): ("/sign", None, 303, 200, 200),  # the desk sign: signed in only
    ("GET", "/api/models/{name}"): ("/api/models/palm_detection_mediapipe_2023feb.onnx", None, 401, 200, 200),
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
            app.write_allowances.clear()  # the limit has its own tests; here it's only the door
            client = stranger() if user is None else let_in(stranger(), user)
            got.append(client.request(method, path, json=body, follow_redirects=False).status_code)
        assert got == expected, f"{method} {route}: no session, member, owner"


def test_the_owner_only_reads_turn_a_member_away():
    member = let_in(stranger(), add_member())
    for path in ("/api/stats", "/api/invites", "/api/accounts"):
        reply = member.get(path)
        assert (reply.status_code, reply.json()) == (403, {"detail": "only the owner can do that"}), path


@pytest.mark.parametrize("path", ["/login", "/join/abc_DEF-123", "/settings", "/me", "/pi", "/track", "/track/test", "/sign", "/people/sam"])
def test_the_page_routes_serve_the_page(path):
    signed_in = let_in(stranger(), find_owner()).get(path)
    signed_out = stranger().get(path, follow_redirects=False)
    assert (signed_in.status_code, signed_in.text) == (200, app.INDEX_PAGE.read_text())
    if path in ("/settings", "/me", "/pi", "/track", "/track/test", "/sign", "/people/sam"):
        assert (signed_out.status_code, signed_out.headers["location"]) == (303, "/login?next=" + quote(path, safe=""))
    else:
        assert (signed_out.status_code, signed_out.text) == (200, app.INDEX_PAGE.read_text())


MODEL_NAMES = {
    "yolo26n_480x640.onnx",
    "face_detection_yunet_2023mar.onnx",
    "palm_detection_mediapipe_2023feb.onnx",
    "handpose_estimation_mediapipe_2023feb.onnx",
}


def test_the_models_route_serves_the_four_models_and_nothing_else():
    client = let_in(stranger(), add_member())
    assert set(app.MODEL_FILES) == MODEL_NAMES
    for name in MODEL_NAMES:
        reply = client.get(f"/api/models/{name}")
        assert reply.status_code == 200, name
        assert reply.content == (MODELS_DIR / name).read_bytes()
        assert reply.headers["cache-control"] == "private, max-age=31536000, immutable"
        assert reply.headers["content-type"] == "application/octet-stream"
    others = ["yolo26n_480x640.onnx.bak", "x.onnx", "..%2Fpaths.py", "%2E%2E%2Fdayanpi%2Fapp.py", "README.md", ""]
    assert [client.get(f"/api/models/{name}").status_code for name in others] == [404] * len(others)
    assert stranger().get("/api/models/yolo26n_480x640.onnx").status_code == 401


def test_every_page_is_cross_origin_isolated_so_the_camera_runs_anywhere():
    client = let_in(stranger(), find_owner())
    page = client.get("/")
    asset = next(path for path in re.findall(r'src="([^"]+\.js)"', page.text))
    pages = [path for (method, _), (path, *_rest) in ACCESS.items() if method == "GET" and not path.startswith(("/api/", "/video", "/assets/"))]
    # The camera's worker is an asset, and in an isolated page a worker only starts when its own script says COEP too.
    paths = [*pages, "/", asset, "/api/focus", "/api/models/yolo26n_480x640.onnx"]
    signed_out = ["/login", "/join/abc_DEF-123", "/me"]
    headers = {path: client.get(path).headers for path in paths} | {f"signed out {path}": stranger().get(path, follow_redirects=False).headers for path in signed_out}
    assert {path: (seen.get("cross-origin-opener-policy"), seen.get("cross-origin-embedder-policy")) for path, seen in headers.items()} == {
        path: ("same-origin", "require-corp") for path in headers
    }
    assert {"/", "/me", "/settings", "/pi", "/track", "/track/test", "/sign", "/login"} <= set(pages) | {"/"}


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


def test_a_token_asked_for_before_a_password_change_is_never_made_after_it(monkeypatch):
    # The middleware lets a session in at the headers; a held-back body lands in the handler after the change.
    found = auth_routes.find_viewer

    def find_then_change_password(request, now):
        viewer = found(request, now)
        auth_routes.accounts.change_password(viewer.user.id, AUTH[1], "")
        return viewer

    with open_client() as owner:
        monkeypatch.setattr(auth_routes, "find_viewer", find_then_change_password)
        made = owner.post("/api/tokens", json={"name": "mac"})
    assert (made.status_code, made.json()) == (401, {"detail": "sign in first"})
    assert auth_routes.accounts.list_tokens(find_owner().id) == []


def test_a_members_token_reports_to_their_own_desk_and_manages_only_their_tokens(fresh_mac_tracking):
    from dayanpi.focus.tracker import format_day

    owner_token = auth_routes.accounts.create_token(make_session_hash(find_owner()), "laptop", time.time())
    bo = add_member()
    member = let_in(stranger(), bo)
    made = member.post("/api/tokens", json={"name": "mac"}).json()
    mac = stranger(headers={"Authorization": f"Bearer {made['secret']}"})
    assert mac.post("/api/mac/app", json={"app": "Code"}).json() == {"status": "ok", "changed": True, "enabled": True}
    assert mac.post("/api/mac/tracking", json={"enabled": False}).json() == {"enabled": False}
    assert mac.get("/api/mac/tracking").json() == {"enabled": False}
    today = format_day(time.time())
    assert [(line["event"], line.get("app")) for line in desk_of(bo).log.read_day(today)] == [("mac_app", "Code"), ("mac_tracking", None)]
    assert fresh_mac_tracking.read_day(today) == [], "nothing on the owner's desk"
    assert desk_of(find_owner()).mac_tracking.enabled
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


@contextmanager
def keep_access_lines():
    """The lines uvicorn's access logger lets through, with its filters on, while the block runs."""
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
        yield seen
    finally:
        access.removeHandler(handler)
        access.setLevel(level)
        access.disabled = disabled


def log_access(method, path, code):
    """uvicorn's own access line: client, method, path with query, HTTP version, status."""
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "100.64.0.1:51000", method, path, "1.1", code)


def test_the_access_log_never_shows_an_invite_code():
    with keep_access_lines() as seen:
        # A stray "/" on a pasted link misses the join page, so the sign-in redirect carries the code in its query.
        redirect = stranger().get("/join/SECRETcode-123/", follow_redirects=False).headers["location"]
        for path in ("/join/SECRETcode-123", "/join/SECRETcode-123/", redirect, "/login?next=/join/SECRETcode-123&x=1", "/api/focus"):
            log_access("GET", path, 200)
    assert redirect == "/login?next=%2Fjoin%2FSECRETcode-123%2F"
    assert [line.split('"')[1] for line in seen] == [
        "GET /join/… HTTP/1.1",
        "GET /join/… HTTP/1.1",
        "GET /login?next=%2Fjoin%2F… HTTP/1.1",
        "GET /login?next=/join/…&x=1 HTTP/1.1",
        "GET /api/focus HTTP/1.1",
    ]
    assert not any("SECRET" in line for line in seen)



def test_the_access_log_leaves_out_what_comes_every_second():
    with keep_access_lines() as seen:
        for method, path, code in (
            ("GET", "/api/people/sam/picture?at=1763250000.5", 200),
            ("GET", "/api/people/sam/picture?at=1763250001.5", 404),  # not sharing right now
            ("POST", "/api/track/reading", 200),
            ("POST", "/api/track/picture", 200),
            ("POST", "/api/todos", 429),
            ("POST", "/api/login", 429),
            ("POST", "/api/track/reading", 429),
            ("GET", "/api/people/sam/picture", 401),
            ("POST", "/api/track/reading", 409),
            ("POST", "/api/login", 401),
            ("POST", "/api/login", 200),
            ("POST", "/api/join", 404),
            ("POST", "/api/todos", 200),
            ("GET", "/api/people/sam", 200),
            ("GET", "/api/focus", 500),
            ("GET", "/join/SECRETcode-123", 200),
        ):
            log_access(method, path, code)
    assert [line.split('"')[1] + line.split('"')[2] for line in seen] == [
        "GET /api/people/sam/picture HTTP/1.1 401",
        "POST /api/track/reading HTTP/1.1 409",
        "POST /api/login HTTP/1.1 401",
        "POST /api/login HTTP/1.1 200",
        "POST /api/join HTTP/1.1 404",
        "POST /api/todos HTTP/1.1 200",
        "GET /api/people/sam HTTP/1.1 200",
        "GET /api/focus HTTP/1.1 500",
        "GET /join/… HTTP/1.1 200",
    ], "the invite code still never shows either"


# Everyone's own desk (study room step 3).


def test_the_first_start_moves_my_data_into_my_folder_and_the_desk_reads_it(caplog):
    from dayanpi.focus.todos import TodoList
    from dayanpi.focus.tracker import FocusLog

    data = app.desks.data_dir
    TodoList(data / "todos.json", FocusLog(data / "focus_log")).add("from before the move", time.time())
    before = {path.relative_to(data).as_posix(): path.read_bytes() for path in data.rglob("*") if path.is_file() and path.name != "accounts.db"}
    with caplog.at_level(logging.INFO, logger="dayanpi"):
        with open_client() as client:
            listed = client.get("/api/todos").json()
    folder = data / "users" / find_owner().username
    after = {path.relative_to(folder).as_posix(): path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    assert after == before, "the same files, byte for byte"
    assert not (data / "todos.json").exists() and not (data / "focus_log").exists()
    assert [item["text"] for item in listed["open"]] == ["from before the move"]
    assert [record.getMessage() for record in caplog.records if record.getMessage().startswith("moved ")] == [
        f"moved focus_log, todos.json from {data} into {folder}"
    ]


def test_every_desk_route_answers_with_your_own_desk_and_never_mine():
    from dayanpi.focus.tracker import format_day

    now = time.time()
    today, yesterday = format_day(now), format_day(now - 86400)
    owner, bo = find_owner(), add_member()
    mine = desk_of(owner)
    write_app_samples(mine.log, today, now - 600, "Code", 4)
    mine.days_dir.mkdir(parents=True)
    (mine.days_dir / f"{yesterday}.md").write_text("---\nfocus_minutes: 95\n---\n\n# Mine\n")
    with open_client() as me:
        member = let_in(stranger(), bo)
        my_item = me.post("/api/todos", json={"text": "mine"}).json()["item"]["id"]
        their_item = member.post("/api/todos", json={"text": "theirs"}).json()["item"]["id"]
        assert member.patch(f"/api/todos/{their_item}", json={"current": True}).status_code == 200
        reads = {
            "todos": [item["text"] for item in member.get("/api/todos").json()["open"]],
            "focus": [item["text"] for item in member.get("/api/focus").json()["todos"]["open"]],
            "apps": member.get("/api/apps").json()["apps"],
            "month": yesterday in member.get(f"/api/days?month={yesterday[:7]}").json()["days"],
            "page": member.get(f"/api/days/{yesterday}").status_code,
        }
        changes = [member.patch(f"/api/todos/{my_item}", json={"done": True}).status_code, delete(member, f"/api/todos/{my_item}").status_code]
        member.post("/api/mac/tracking", json={"enabled": False})
        member.post("/api/mac/app", json={"app": "Notes"})
        my_view = me.get("/api/focus").json()
    assert reads == {"todos": ["theirs"], "focus": ["theirs"], "apps": [], "month": False, "page": 404}
    assert changes == [404, 404], "my to-do is no to-do of theirs"
    assert [item["text"] for item in my_view["todos"]["open"]] == ["mine"] and my_view["todos"]["current"] is None
    assert my_view["mac_tracking"] is True and my_view["app"] is None
    assert [item["text"] for item in desk_of(bo).todos.snapshot(now)["open"]] == ["theirs"]
    assert desk_of(bo).mac_tracking.enabled is False


def test_members_change_their_own_desk_but_the_owners_things_stay_403():
    with open_client("member") as member:
        assert member.post("/api/todos", json={"text": "my own"}).status_code == 200
        assert member.post("/api/mac/tracking", json={"enabled": False}).json() == {"enabled": False}
        owner_only = [member.get(path).status_code for path in ("/api/stats", "/api/invites", "/api/accounts")]
        owner_writes = [member.post("/api/invites", json={}).status_code, delete(member, f"/api/accounts/{find_owner().id}").status_code]
        camera = [member.get("/video").status_code, member.get("/video/side").status_code]
    assert owner_only == [403, 403, 403]
    assert owner_writes == [403, 403]
    assert camera == [404, 404]


def test_the_cameras_and_the_peace_sign_only_touch_my_desk(monkeypatch):
    from dayanpi.focus.tracker import FocusUpdate, format_day

    mine, theirs = use_owner_desk(monkeypatch), desk_of(add_member())
    monkeypatch.setattr(app.voice, "say", lambda text: True)
    now = time.time()
    for desk in (mine, theirs):
        item = desk.todos.add("counting", now)["id"]
        desk.todos.change(item, now, current=True)
    for second in range(3):
        app.handle_focus_update(mine, FocusUpdate(state="working"), now + second)
    app.handle_gesture(mine, "peace", now + 3)
    seconds = {desk.username: [item["seconds"] for item in desk.todos.snapshot(now + 4)["open"]] for desk in (mine, theirs)}
    assert seconds == {mine.username: [2], theirs.username: [0]}, "three checks a second apart are two seconds"
    gestures = {desk.username: [line["event"] for line in desk.log.read_day(format_day(now)) if line["event"] == "gesture"] for desk in (mine, theirs)}
    assert gestures == {mine.username: ["gesture"], theirs.username: []}


def test_the_worker_feeds_my_desk(monkeypatch):
    class FakeScanner:
        def scan(self, image):
            raise AssertionError("no frames here")

    monkeypatch.setattr(focus_worker, "build_scanner", lambda: FakeScanner())
    with open_client():
        assert app.worker._tracker is desk_of(find_owner()).tracker


def test_a_members_desk_waits_for_a_browsers_camera_and_gets_none_of_mine():
    with open_client("member") as member:
        app.owner_desk.last_spoken = {"text": "my peace sign", "at": time.time()}
        status = member.get("/api/focus").json()
    camera_parts = {key: status[key] for key in ("enabled", "side_camera", "side_camera_running", "overlay", "side_overlay", "gesture", "spoken", "voice", "camera_access")}
    voice = {"enabled": app.voice.enabled, "backend": app.voice.backend, "problem": None}
    assert camera_parts == {**app.NO_CAMERA, "enabled": True, "spoken": None, "voice": voice, "camera_access": "owner_only"}
    assert (status["camera_source"], status["camera_paused"]) == ("browser", False)
    assert (status["state"], status["camera_ok"], status["last_check"]) == ("unknown", False, None)


def test_the_status_carries_my_cameras_and_voice_and_theirs_none(monkeypatch):
    mine, theirs = use_owner_desk(monkeypatch), desk_of(add_member())
    now = time.time()
    statuses = {desk.username: app.build_desk_status(desk, now) for desk in (mine, theirs)}
    assert statuses[mine.username]["voice"] == {"enabled": app.voice.enabled, "backend": app.voice.backend, "problem": app.voice.problem}
    assert {key: statuses[theirs.username][key] for key in app.NO_CAMERA} == {**app.NO_CAMERA, "enabled": True}
    assert (statuses[mine.username]["camera_source"], statuses[theirs.username]["camera_source"]) == ("pi", "browser")


SEEN = {"person": 0.91, "phone": 0.0, "elapsed_ms": 140.5}


def test_a_browser_reading_feeds_the_senders_own_desk_about_once_a_second():
    from dayanpi.focus.tracker import format_day

    with open_client("member") as member:
        replies = [member.post("/api/track/reading", json=SEEN) for _ in range(3)]
        theirs = member.get("/api/focus").json()
        mine = let_in(stranger(), find_owner()).get("/api/focus").json()
        signed_out = stranger().post("/api/track/reading", json=SEEN)
        member_desk = app.desks.open("bo", time.time())
    assert [reply.status_code for reply in replies] == [200, 200, 429], "two close together, then one a second"
    assert replies[1].json() == {"state": "working", "seconds_in_state": 0.0, "paused": False, "spoken": None, "send_picture": False}
    assert replies[2].json() == {"detail": "one reading a second"}
    assert (theirs["state"], theirs["camera_ok"], theirs["last_check"]["person"], theirs["last_check"]["elapsed_ms"]) == ("working", True, 0.91, 140.5)
    assert (mine["state"], mine["last_check"]) == ("unknown", None)
    assert signed_out.status_code == 401
    states = [line["state"] for line in member_desk.log.read_day(format_day(time.time())) if line["event"] == "state"]
    assert states == ["working"]


@pytest.mark.parametrize(
    "body",
    [
        {**SEEN, "person": 1.01},
        {**SEEN, "phone": -0.1},
        {**SEEN, "elapsed_ms": 60_001},
        {**SEEN, "sign": "fist"},
        {**SEEN, "picture": "A" * (PICTURE_MAX_BASE64 + 1)},  # a picture is allowed (step 7), but never a big one
        {"person": 0.9, "phone": 0.0},
        {**SEEN, "person": "0.9x"},
    ],
)
def test_a_browser_reading_is_checked_and_bounded(body):
    with open_client("member") as member:
        reply = member.post("/api/track/reading", json=body)
        nan = member.post("/api/track/reading", content=b'{"person": NaN, "phone": 0, "elapsed_ms": 1}', headers={"Content-Type": "application/json"})
        state = member.get("/api/focus").json()["last_check"]
    assert (reply.status_code, nan.status_code, state) == (422, 422, None)


def test_readings_only_count_for_a_desk_on_the_browser_and_only_my_desk_can_pick_the_pi():
    with open_client() as client, open_client("member") as member:
        on_the_pi = client.post("/api/track/reading", json=SEEN)
        paused_on_the_pi = client.post("/api/track/pause", json={})
        member_pi = member.post("/api/track/source", json={"source": "pi"})
        member_browser = member.post("/api/track/source", json={"source": "browser"})
        feeding_before = app.worker._is_feeding() if app.worker else None
        picked = client.post("/api/track/source", json={"source": "browser"})
        source_after = client.get("/api/focus").json()["camera_source"]
        on_the_browser = client.post("/api/track/reading", json=SEEN)
        back = client.post("/api/track/source", json={"source": "pi"}).json()
    assert (on_the_pi.status_code, on_the_pi.json()) == (409, {"detail": "this desk uses the Pi's cameras"})
    assert paused_on_the_pi.status_code == 409
    assert (member_pi.status_code, member_pi.json()) == (403, {"detail": "only the owner's desk has the Pi's cameras"})
    assert (member_browser.status_code, member_browser.json()) == (200, {"source": "browser", "picture": "browser", "pi_camera": "front"})
    assert (picked.json(), source_after, on_the_browser.status_code, back) == ({"source": "browser", "picture": "browser", "pi_camera": "front"}, "browser", 200, {"source": "pi", "picture": "pi", "pi_camera": "front"})
    assert feeding_before is None, "no models in the tests, so no worker"


def test_the_pi_worker_only_feeds_my_desk_while_i_have_the_pi_cameras_picked(monkeypatch):
    class FakeScanner:
        def scan(self, image):
            raise AssertionError("no frames here")

    monkeypatch.setattr(focus_worker, "build_scanner", lambda: FakeScanner())
    with open_client() as client:
        feeding = [app.worker._is_feeding()]
        client.post("/api/track/source", json={"source": "browser"})
        feeding.append(app.worker._is_feeding())
        client.post("/api/track/source", json={"source": "pi"})
        feeding.append(app.worker._is_feeding())
    assert feeding == [True, False, True]


def test_pause_says_paused_until_the_next_reading():
    with open_client("member") as member:
        member.post("/api/track/reading", json=SEEN)
        member.post("/api/track/reading", json=SEEN)
        paused = member.post("/api/track/pause", json={}).json()
        status = member.get("/api/focus").json()
        time.sleep(1.05)
        resumed = member.post("/api/track/reading", json=SEEN).json()
    assert paused == {"state": "unknown", "seconds_in_state": 0.0, "paused": True, "spoken": None, "send_picture": False}
    assert (status["camera_paused"], status["camera_ok"]) == (True, False)
    assert resumed["paused"] is False


def test_a_quiet_browser_desk_goes_unknown_but_my_pi_desk_isnt_ticked(monkeypatch):
    with open_client("member") as member:
        member.post("/api/track/reading", json=SEEN)
        member.post("/api/track/reading", json=SEEN)
        theirs = app.desks.open("bo", time.time())
        mine = app.owner_desk
        my_last_update = mine.tracker._last_update_at
        app.tick_browser_desks(time.time() + 31)
        their_state = theirs.tracker.status(time.time() + 31)["state"]
    assert their_state == "unknown"
    assert mine.tracker._last_update_at == my_last_update, "the Pi's worker feeds my desk, not the ticks"


def test_a_peace_sign_from_the_browser_is_on_their_desk_and_their_pill_only(monkeypatch):
    from dayanpi.focus.tracker import format_day

    said = []
    monkeypatch.setattr(app.voice, "say", lambda text: said.append(text) or True)
    with open_client("member") as member:
        theirs = app.desks.open("bo", time.time())
        theirs.todos.add("read chapter 3", time.time())
        member.post("/api/track/reading", json={**SEEN, "sign": "peace"})
        time.sleep(1.05)
        member.post("/api/track/reading", json={**SEEN, "sign": "peace"})
        status = member.get("/api/focus").json()
        mine = let_in(stranger(), find_owner()).get("/api/focus").json()
    gestures = [line for line in theirs.log.read_day(format_day(time.time())) if line["event"] == "gesture"]
    mine_logged = [line for line in app.owner_desk.log.read_day(format_day(time.time())) if line["event"] == "gesture"]
    assert [line["name"] for line in gestures] == ["peace"] and mine_logged == []
    assert status["gesture"]["name"] == "peace"
    assert "read chapter 3" in status["spoken"]["text"] and status["spoken"]["speaking"] is False
    assert (mine["gesture"], mine["spoken"], said) == (None, None, [])


def make_clip_voice(tmp_path):
    """A working Piper voice whose clips are made at once: "RIFF" and the phrase, so a test can tell them apart."""
    from dayanpi.hardware.voice import VoiceAnnouncer, VoiceSettings

    model = tmp_path / "voice.onnx"
    model.write_bytes(b"not a real model")
    model.with_name("voice.onnx.json").write_text('{"audio": {"sample_rate": 22050}}')
    speaker = VoiceAnnouncer(
        VoiceSettings(backend="piper", piper_model=model, audio_device=None),
        runner=lambda job: None,
        find_program=lambda name: f"/usr/bin/{name}",
        piper_installed=lambda: True,
        synthesizer=lambda job, rate: b"RIFF" + job.text_input,
    )
    return speaker


def wait_for_clip(username):
    deadline = time.monotonic() + 5
    while not app.clips.has(username, time.time()) and time.monotonic() < deadline:
        time.sleep(0.01)
    return app.clips.has(username, time.time())


def test_bedtime_is_per_person_and_kept_in_their_folder(monkeypatch):
    with open_client() as client, open_client("member") as member:
        client.post("/api/voice", json={"bedtime": "22:30"})
        before = (client.get("/api/focus").json()["bedtime"], member.get("/api/focus").json()["bedtime"])
        changed = member.post("/api/voice", json={"bedtime": "23:15"})
        after = (client.get("/api/focus").json()["bedtime"], member.get("/api/focus").json()["bedtime"])
        theirs = app.desks.open("bo", time.time())
        coach_text = app.find_coach(theirs).pick(time.time()).text
        extra = member.post("/api/voice", json={"bedtime": "23:15", "volume": 11})
    assert before == ("22:30", "00:00")
    assert (changed.status_code, changed.json()) == (200, {"bedtime": "23:15", "output": "computer"})
    assert after == ("22:30", "23:15")
    assert json.loads((theirs.folder / "voice.json").read_text()) == {"bedtime": "23:15", "output": None}
    assert "until bed" in coach_text or "past your bedtime" in coach_text
    assert app.find_bedtime(theirs) == 23 * 60 + 15
    assert extra.status_code == 422


def test_each_persons_peace_sign_speaks_their_own_todos(monkeypatch):
    from dayanpi.focus.tracker import format_day

    said = []
    monkeypatch.setattr(app.voice, "say", lambda text: said.append(text) or True)
    mine, theirs = use_owner_desk(monkeypatch), desk_of(add_member())
    now = time.time()
    mine.todos.add("my report", now)
    theirs.todos.add("their essay", now)
    app.handle_gesture(theirs, "peace", now)
    app.handle_gesture(mine, "peace", now + 1)
    assert "their essay" in theirs.last_spoken["text"] and "my report" not in theirs.last_spoken["text"]
    assert "my report" in mine.last_spoken["text"] and "their essay" not in mine.last_spoken["text"]
    assert said == [mine.last_spoken["text"]], "only mine goes to the Pi's speaker"
    lines = [line for line in theirs.log.read_day(format_day(now)) if line["event"] == "gesture"]
    assert [(line["name"], line["spoken"]) for line in lines] == [("peace", "template")]


def test_only_my_desk_can_pick_the_pi_speaker():
    with open_client() as client, open_client("member") as member:
        mine_before = client.get("/api/focus").json()["voice_output"]
        refused = member.post("/api/voice", json={"output": "pi"})
        theirs = member.post("/api/voice", json={"output": "computer"}).json()
        mine_computer = client.post("/api/voice", json={"output": "computer"}).json()
        mine_back = client.post("/api/voice", json={"output": "pi"}).json()
    assert mine_before == "pi"
    assert (refused.status_code, refused.json()) == (403, {"detail": "only the owner's desk has the Pi's speaker"})
    assert theirs["output"] == "computer"
    assert (mine_computer["output"], mine_back["output"]) == ("computer", "pi")


def test_a_clip_waits_in_memory_for_its_own_person_once_and_never_touches_the_disk(monkeypatch, tmp_path, caplog):
    (tmp_path / "voice").mkdir()
    monkeypatch.setattr(app, "voice", make_clip_voice(tmp_path / "voice"))
    with caplog.at_level(logging.INFO), open_client() as client, open_client("member") as member:
        tested = member.post("/api/voice/test", json={}).json()
        ready = wait_for_clip("bo")
        status = member.get("/api/focus").json()["spoken"]
        not_mine = client.get("/api/voice/clip")
        signed_out = stranger().get("/api/voice/clip")
        clip = member.get("/api/voice/clip")
        again = member.get("/api/voice/clip")
        after = member.get("/api/focus").json()["spoken"]
        app.clips.put("bo", b"RIFF old", time.time() - 61)
        stale = member.get("/api/voice/clip")
    assert tested == {"output": "computer", "voice": True} and ready
    assert (status["text"], status["clip"], status["speaking"]) == (app.TEST_LINE, True, False)
    assert (not_mine.status_code, signed_out.status_code) == (404, 401), "my clip shelf is empty, and strangers get nothing"
    assert (clip.status_code, clip.headers["content-type"], clip.headers["cache-control"]) == (200, "audio/wav", "no-store")
    assert clip.content == b"RIFF" + (app.TEST_LINE + "\n").encode()
    assert (again.status_code, after["clip"], stale.status_code) == (404, False, 404), "once, and only for a minute"
    assert [path for path in tmp_path.rglob("*") if path.is_file() and path.read_bytes().startswith(b"RIFF")] == []
    assert app.TEST_LINE not in caplog.text


def test_a_newer_message_never_gets_an_older_ones_clip(monkeypatch, tmp_path):
    (tmp_path / "voice").mkdir()
    speaker = make_clip_voice(tmp_path / "voice")
    first_done = threading.Event()

    def slow_first(job, rate):
        if b"first" in job.text_input:
            first_done.wait(timeout=5)  # still making the first clip when the second message comes
        return b"RIFF" + job.text_input

    speaker._synthesizer = slow_first
    monkeypatch.setattr(app, "voice", speaker)
    theirs = desk_of(add_member())
    speaker.start()
    try:
        app.speak_to(theirs, "first", time.time())
        app.speak_to(theirs, "second", time.time() + 1)  # one clip a person at a time: dropped while the first is made
        first_done.set()
        deadline = time.monotonic() + 5
        while "bo" in speaker._clip_owners and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not app.clips.has("bo", time.time()), "the first's clip never stands in for the second"
        app.speak_to(theirs, "third", time.time() + 2)
        assert wait_for_clip("bo")
    finally:
        speaker.stop()
    assert app.clips.take("bo", time.time()) == b"RIFFthird\n"


def test_the_voice_test_waits_ten_seconds_per_desk():
    bo, sam = add_member("bo"), add_member("sam")
    client = let_in(stranger(), bo)
    first = client.post("/api/voice/test", json={})
    second = client.post("/api/voice/test", json={})
    theirs = let_in(stranger(), sam).post("/api/voice/test", json={})
    desk_of(bo).voice_tested_at -= app.VOICE_TEST_EVERY_S
    later = client.post("/api/voice/test", json={})
    assert [first.status_code, theirs.status_code, later.status_code] == [200, 200, 200], "sam's desk has its own wait"
    assert (second.status_code, second.json()) == (429, {"detail": "one test every 10 s"})
    assert 1 <= int(second.headers["retry-after"]) <= 10


def test_with_the_voice_off_the_pill_gets_the_words_and_no_clip():
    with open_client("member") as member:
        tested = member.post("/api/voice/test", json={}).json()
        spoken = member.get("/api/focus").json()["spoken"]
        clip = member.get("/api/voice/clip")
    assert tested == {"output": "computer", "voice": False}
    assert (spoken["text"], spoken["clip"], spoken["speaking"]) == (app.TEST_LINE, False, False)
    assert clip.status_code == 404


def test_the_test_line_goes_to_the_pi_speaker_when_i_have_it(monkeypatch):
    said = []
    monkeypatch.setattr(app.voice, "say", lambda text: said.append(text) or True)
    with open_client() as client:
        tested = client.post("/api/voice/test", json={}).json()
    assert (tested["output"], said) == ("pi", [app.TEST_LINE])


def test_day_pages_are_written_for_every_desk():
    from dayanpi.focus.tracker import format_day

    yesterday_ts = time.time() - 86400
    yesterday = format_day(yesterday_ts)
    desks = [desk_of(find_owner()), desk_of(add_member())]
    for desk in desks:
        desk.log.write({"ts": yesterday_ts, "day": yesterday, "event": "todo", "action": "added", "id": "x", "text": desk.username, "seconds": 0})
    app.write_day_pages(time.time())
    assert [(desk.days_dir / f"{yesterday}.md").is_file() for desk in desks] == [True, True]


def test_removing_someone_moves_their_desk_aside_and_the_name_starts_empty():
    from dayanpi.focus.tracker import format_day

    def join_as_bo(owner_client):
        code = owner_client.post("/api/invites", json={}).json()["code"]
        newcomer = stranger()
        joined = newcomer.post("/api/join", json={"code": code, "display_name": "Bo", "username": "bo", "password": MEMBER_PASSWORD})
        return newcomer, joined.json()["user"]["id"]

    with open_client() as owner:
        bo, bo_id = join_as_bo(owner)
        assert "bo" in [desk.username for desk in app.desks.list()], "a desk the moment they join"
        bo.post("/api/todos", json={"text": "the first bo's"})
        assert delete(owner, f"/api/accounts/{bo_id}").status_code == 200
        again, _ = join_as_bo(owner)
        fresh = again.get("/api/todos").json()["open"]
    removed = app.desks.users_dir / "removed" / f"bo-{format_day(time.time())}"
    assert "the first bo's" in (removed / "todos.json").read_text(), "moved aside, never deleted"
    assert fresh == [], "the same username starts empty"


# ----- someone's desk, nudges and the group calendar (study room step 6, part 2) -----

SECRETS = {
    "today": ["phone_seconds", "segments"],
    "todo_list": ["secret plan", "older secret"],
    "apps": ["SecretApp"],
    "sites": ["secret.example"],
    "history": ["joined_at", "total_minutes"],
}


def make_sams_desk():
    """Sam's desk with something to find in every piece: to-dos, a Mac app on a site, and a past day's page."""
    sam = add_member("sam")
    desk = desk_of(sam)
    now = time.time()
    plan = desk.todos.add("secret plan", now)
    desk.todos.change(plan["id"], now, current=True)
    desk.todos.change(desk.todos.add("older secret", now)["id"], now, done=True)
    desk.tracker.record_app("SecretApp", now, site="secret.example")
    write_app_samples(desk.log, format_day(now), now - 100, "SecretApp", 3, site="secret.example")
    desk.days_dir.mkdir(parents=True)
    (desk.days_dir / f"{format_day(now)[:7]}-01.md").write_text("---\nfocus_minutes: 77\n---\n")
    return sam, desk


@pytest.mark.parametrize(
    "switches, pieces",
    [
        ({"apps": True, "sites": True, "video": True}, {"today", "todo_list", "apps", "app_youtube", "sites", "history", "video"}),
        ({"focus": False, "apps": False}, {"todo_list", "history"}),  # TheirDeskLess: to-dos and history only
        ({"apps": True}, {"today", "todo_list", "apps", "history"}),  # sites stay off, so no YouTube part either
        ({"apps": False, "sites": True}, {"today", "todo_list", "history"}),  # sites without apps counts for nothing
        ({"focus": False, "todos": False, "history": False}, set()),
    ],
)
def test_their_desk_has_only_the_pieces_they_share(switches, pieces):
    sam, desk = make_sams_desk()
    desk.sharing.update(switches)
    reply = let_in(stranger(), find_owner()).get("/api/people/sam")
    their = reply.json()
    seat_keys = {"username", "name", "here", "state", "seconds_in_state", "shares", "focus_seconds", "todos", "app", "site", "nudge", "here_since", "picture", "hidden"}
    assert reply.status_code == 200
    assert set(their) - seat_keys == pieces
    for piece, texts in SECRETS.items():
        for text in texts:
            assert (text in reply.text) == (piece in pieces), f"{text} with {piece} {'on' if piece in pieces else 'off'}"
    if "history" in pieces:
        assert their["history"]["days"][f"{format_day(time.time())[:7]}-01"] == 77
        assert (format_day(time.time()) in their["history"]["days"]) == ("today" in pieces), "today's live minutes need focus"
    if "app_youtube" in pieces:
        assert their["sites"] == [{"site": "secret.example", "seconds": 90.0}]


def test_nobodys_desk_is_a_404_and_yours_is_what_the_room_sees():
    owner = find_owner()
    desk_of(owner).sharing.update({"todos": False})
    client = let_in(stranger(), owner)
    assert client.get("/api/people/nobody").status_code == 404
    mine = client.get(f"/api/people/{owner.username}").json()
    assert "todo_list" not in mine and "todos" not in mine


def put_on_the_phone(monkeypatch, desk, seconds=400):
    """The desk's tracker says phone for this long, and just checked them (so they're here)."""
    real = desk.tracker.status
    monkeypatch.setattr(desk.tracker, "status", lambda now: {**real(now), "state": "phone", "seconds_in_state": seconds, "last_check": {"at": now}})


def test_a_member_nudges_me_on_the_pis_speaker(monkeypatch):
    member = add_member()
    mine = use_owner_desk(monkeypatch)
    put_on_the_phone(monkeypatch, mine)
    said = []
    monkeypatch.setattr(app.voice, "say", lambda text: said.append(text))
    reply = let_in(stranger(), member).post("/api/nudge", json={"username": find_owner().username})
    assert (reply.status_code, reply.json()["wait_s"]) == (200, 600)
    assert said == ["Bo says put the phone down"]
    assert mine.last_spoken["kind"] == "nudge"
    assert mine.last_nudged["by"] == "bo"


def test_i_nudge_a_member_on_their_own_computer(monkeypatch):
    sam = add_member("sam")
    desk = desk_of(sam)
    put_on_the_phone(monkeypatch, desk)
    rendered = []
    monkeypatch.setattr(app.voice, "render", lambda text, sink, owner: rendered.append(text))
    monkeypatch.setattr(app.voice, "say", lambda text: pytest.fail("a member's nudge never plays on the Pi"))
    reply = let_in(stranger(), find_owner()).post("/api/nudge", json={"username": "sam"})
    assert reply.status_code == 200
    assert rendered == ["tester says put the phone down"]
    spoken = app.describe_spoken(desk, time.time())
    assert (spoken["text"], spoken["kind"]) == ("tester says put the phone down", "nudge")


def test_nudges_wait_ten_minutes_per_person_and_only_on_the_phone(monkeypatch):
    sam = add_member("sam")
    desk = desk_of(sam)
    monkeypatch.setattr(app.voice, "render", lambda text, sink, owner: None)
    owner = let_in(stranger(), find_owner())
    other = let_in(stranger(), add_member("al"))
    assert owner.post("/api/nudge", json={"username": "sam"}).status_code == 409, "not on the phone"
    put_on_the_phone(monkeypatch, desk, seconds=299)
    assert owner.post("/api/nudge", json={"username": "sam"}).status_code == 409, "not for 5 minutes yet"
    put_on_the_phone(monkeypatch, desk)
    assert owner.post("/api/nudge", json={"username": "sam"}).status_code == 200
    again = other.post("/api/nudge", json={"username": "sam"})
    assert (again.status_code, again.json()["detail"]) == (429, "nudged a few minutes ago"), "one per person, whoever asks"
    assert 590 <= int(again.headers["Retry-After"]) <= 601
    seat = app.seat_desk(desk, "Sam", app.build_desk_status(desk, time.time()), time.time())
    assert seat["nudge"]["wait_s"] > 590 and seat["nudge"]["age_s"] < 5
    desk.last_nudged["at"] -= app.NUDGE_EVERY_S
    assert other.post("/api/nudge", json={"username": "sam"}).status_code == 200
    assert owner.post("/api/nudge", json={"username": find_owner().username}).status_code == 400, "not yourself"
    assert owner.post("/api/nudge", json={"username": "nobody"}).status_code == 404


def test_nobody_can_nudge_someone_who_turned_nudges_off(monkeypatch):
    sam = add_member("sam")
    desk = desk_of(sam)
    put_on_the_phone(monkeypatch, desk)
    let_in(stranger(), sam).post("/api/sharing", json={"nudges": False})
    reply = let_in(stranger(), find_owner()).post("/api/nudge", json={"username": "sam"})
    assert reply.status_code == 409
    assert desk.last_nudged is None and desk.last_spoken is None
    assert "nudge" not in app.seat_desk(desk, "Sam", app.build_desk_status(desk, time.time()), time.time())


# ----- hiding an offline seat -----


def test_anyone_hides_an_offline_seat_but_never_their_own_or_someone_here(monkeypatch, caplog):
    owner, sam = find_owner(), add_member("sam")
    me, member = let_in(stranger(), owner), let_in(stranger(), sam)
    with caplog.at_level(logging.INFO):
        assert member.post("/api/room/hide", json={"username": owner.username}).json() == {"username": owner.username, "hidden": True}
        assert me.post("/api/room/show", json={"username": owner.username}).status_code == 400, "not yourself either"
        assert me.post("/api/room/hide", json={"username": "sam"}).status_code == 200
        assert me.post("/api/room/show", json={"username": "sam"}).json() == {"username": "sam", "hidden": False}
    assert f"sam hid {owner.username}'s seat" in caplog.text
    assert f"{owner.username} hid sam's seat" in caplog.text and f"{owner.username} showed sam's seat" in caplog.text
    assert desk_of(owner).seat.read() == {"hidden": True} and desk_of(sam).seat.read() == {"hidden": False}

    yours = member.post("/api/room/hide", json={"username": "sam"})
    assert (yours.status_code, yours.json()["detail"]) == (400, "that's you")
    assert member.post("/api/room/hide", json={"username": "nobody"}).status_code == 404
    desk_of(sam).seen_at = time.time()
    here = me.post("/api/room/hide", json={"username": "sam"})
    assert (here.status_code, here.json()["detail"]) == (409, "they're here right now")
    put_on_the_phone(monkeypatch, desk_of(owner))  # the camera just checked me: here without the site open
    assert member.post("/api/room/hide", json={"username": owner.username}).status_code == 409


def test_a_hidden_seat_stays_hidden_through_a_restart_and_comes_back_once_theyre_here(real_server, monkeypatch, tmp_path):
    owner, sam = find_owner(), add_member("sam")
    let_in(stranger(), owner).post("/api/room/hide", json={"username": "sam"})
    monkeypatch.setattr(app, "desks", Desks(tmp_path))  # a restart: every desk opened again from its folder
    desk_of(owner), desk_of(sam)
    room = make_room(monkeypatch, time.time())
    assert [(seat["username"], seat["hidden"]) for seat in room["seats"]] == [(owner.username, False), ("sam", True)], "still a seat of its own"
    with httpx.stream("GET", real_server + "/api/stream", headers=session_header(owner), timeout=3) as response:
        [event] = read_events(response, 1)
    assert event["room"] == room

    desk_of(sam).seen_at = time.time()  # their site opens
    [_, seat] = make_room(monkeypatch, time.time())["seats"]
    assert (seat["here"], seat["hidden"]) == (True, False)
    assert json.loads((desk_of(sam).folder / "seat.json").read_text()) == {"hidden": False}
    assert let_in(stranger(), owner).get("/api/people/sam").status_code == 200, "their desk opens all along"


def test_the_day_page_has_the_others_who_share_focus_and_history():
    owner, sam, al = find_owner(), add_member("sam"), add_member("al")
    now = time.time()
    day = f"{format_day(now)[:7]}-01" if format_day(now)[8:] != "01" else f"{format_day(now)[:7]}-02"
    for user, minutes in ((owner, 30), (sam, 108), (al, 125)):
        desk = desk_of(user)
        desk.days_dir.mkdir(parents=True)
        (desk.days_dir / f"{day}.md").write_text(f"---\nfocus_minutes: {minutes}\n---\n")
    desk_of(al).sharing.update({"history": False})
    mine = let_in(stranger(), owner).get(f"/api/days/{day}").json()
    sams = let_in(stranger(), sam).get(f"/api/days/{day}").json()
    assert mine["others"] == [{"name": "Sam", "focus_minutes": 108}], "Al keeps history private"
    assert sams["others"] == [{"name": "tester", "focus_minutes": 30}]
    desk_of(sam).sharing.update({"focus": False})
    assert let_in(stranger(), owner).get(f"/api/days/{day}").json()["others"] == []


# ----- the seats' small pictures (study room step 7) -----


def make_jpeg(width=320, height=180) -> bytes:
    import cv2
    import numpy as np

    frame = np.full((height, width, 3), 90, dtype=np.uint8)
    cv2.circle(frame, (width // 2, height // 2), height // 4, (200, 180, 160), -1)
    return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 50])[1].tobytes()


def as_base64(jpeg: bytes) -> str:
    import base64

    return base64.b64encode(jpeg).decode("ascii")


def read_with_picture(client, picture: str, person: float = 0.9) -> dict:
    reply = client.post("/api/track/reading", json={"person": person, "phone": 0, "elapsed_ms": 120, "picture": picture})
    assert reply.status_code == 200, reply.text
    return reply.json()


def list_files(folder) -> list[str]:
    return sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file())


def test_a_browser_sends_a_picture_only_while_sharing_video_and_at_the_desk(tmp_path):
    sam = add_member("sam")
    desk = desk_of(sam)
    client = let_in(stranger(), sam)
    picture = as_base64(make_jpeg())
    assert read_with_picture(client, picture)["send_picture"] is False, "video starts off"
    assert desk.picture is None, "the Pi drops a picture nobody asked for"
    client.post("/api/sharing", json={"video": True})
    desk.browser._tokens = 2  # the reading bucket allows two at once; the test sends more than one second's worth
    reply = read_with_picture(client, picture)
    assert (reply["state"], reply["send_picture"]) == ("working", True)
    assert desk.picture is not None and desk.picture["jpeg"] == make_jpeg()

    owner = let_in(stranger(), find_owner())
    served = owner.get("/api/people/sam/picture")
    assert (served.status_code, served.content, served.headers["content-type"]) == (200, make_jpeg(), "image/jpeg")
    assert served.headers["cache-control"] == "no-store" and served.headers["x-content-type-options"] == "nosniff"
    seat = app.seat_desk(desk, "Sam", app.build_desk_status(desk, time.time()), time.time())
    assert seat["picture"]["at"] == desk.picture["at"]
    assert stranger().get("/api/people/sam/picture").status_code == 401, "signed-in room members only"


def test_hiding_video_drops_the_picture_at_once_and_refuses_the_next(monkeypatch):
    sam = add_member("sam")
    desk = desk_of(sam)
    client = let_in(stranger(), sam)
    client.post("/api/sharing", json={"video": True})
    desk.picture = {"jpeg": make_jpeg(), "at": time.time()}
    put_on_the_phone(monkeypatch, desk)
    owner = let_in(stranger(), find_owner())
    assert owner.get("/api/people/sam/picture").status_code == 200

    client.post("/api/sharing", json={"video": False})
    assert desk.picture is None, "hidden means gone, not in 3 seconds"
    assert owner.get("/api/people/sam/picture").status_code == 404
    desk.browser._tokens = 2
    assert read_with_picture(client, as_base64(make_jpeg()))["send_picture"] is False
    assert desk.picture is None, "one that still arrives is dropped"


def test_away_or_unknown_means_no_picture(monkeypatch):
    sam = add_member("sam")
    desk = desk_of(sam)
    desk.sharing.update({"video": True})
    now = time.time()
    app.keep_picture(desk, make_jpeg(), "away", now)
    assert desk.picture is None
    app.keep_picture(desk, make_jpeg(), "working", now)
    assert desk.picture is not None
    real = desk.tracker.status
    monkeypatch.setattr(desk.tracker, "status", lambda at: {**real(at), "state": "unknown", "last_check": {"at": at}})
    assert let_in(stranger(), find_owner()).get("/api/people/sam/picture").status_code == 404, "the Pi serves nothing while away"
    app.keep_picture(desk, make_jpeg(), "unknown", now)
    assert desk.picture is None, "a reading that leaves the desk drops the last picture"


def test_nothing_older_than_three_seconds(monkeypatch):
    sam = add_member("sam")
    desk = desk_of(sam)
    desk.sharing.update({"video": True})
    put_on_the_phone(monkeypatch, desk)
    owner = let_in(stranger(), find_owner())
    desk.picture = {"jpeg": make_jpeg(), "at": time.time() - 2.5}
    assert owner.get("/api/people/sam/picture").status_code == 200
    desk.picture["at"] = time.time() - 3.5
    assert owner.get("/api/people/sam/picture").status_code == 404
    assert app.seat_desk(desk, "Sam", app.build_desk_status(desk, time.time()), time.time())["picture"] is None


def test_a_640_by_360_picture_is_kept_and_a_bigger_one_is_dropped():
    sam = add_member("sam")
    desk = desk_of(sam)
    desk.sharing.update({"video": True})
    client = let_in(stranger(), sam)
    read_with_picture(client, as_base64(make_jpeg()))
    desk.browser._tokens = 2
    assert read_with_picture(client, as_base64(make_jpeg()))["state"] == "working", "a picture is only kept at the desk"
    kept = []
    for size in [(640, 360), (641, 360), (640, 361), (320, 180)]:
        desk.browser._tokens = 2
        reply = read_with_picture(client, as_base64(make_jpeg(*size)))
        kept.append(desk.picture is not None and desk.picture["jpeg"] == make_jpeg(*size))
        assert reply["seconds_in_state"] is not None, "the reading counts either way"
    assert kept == [True, False, False, True], "the seat's own size (and an older, smaller page's) only"


def test_a_reading_with_the_biggest_picture_fits_under_the_body_cap():
    sam = add_member("sam")
    client = let_in(stranger(), sam)
    biggest = {"person": 0.123456789, "phone": 0.987654321, "sign": "peace", "elapsed_ms": 59_999.123456789, "picture": "A" * PICTURE_MAX_BASE64}
    body = json.dumps(biggest).encode()
    assert PICTURE_MAX_BYTES * 4 / 3 <= PICTURE_MAX_BASE64 and len(body) <= app.MAX_BODY_BYTES, f"{len(body)} bytes"
    reply = client.post("/api/track/reading", content=body, headers={"Content-Type": "application/json"})
    assert reply.status_code == 200, "not a 413 and not a 422: the picture isn't a JPEG, so it's dropped and the reading counts"


@pytest.mark.parametrize("sent", ["not base64!", as_base64(b"GIF89a not a jpeg"), as_base64(make_jpeg(1280, 720))])
def test_anything_but_a_small_jpeg_is_dropped_and_the_reading_still_counts(sent):
    sam = add_member("sam")
    desk = desk_of(sam)
    desk.sharing.update({"video": True})
    client = let_in(stranger(), sam)
    desk.browser._tokens = 2
    reply = read_with_picture(client, sent)
    assert reply["seconds_in_state"] is not None
    assert desk.picture is None


def test_a_picture_claiming_a_huge_size_is_dropped_before_anything_decodes_it(monkeypatch):
    from dayanpi.focus import pictures

    real = make_jpeg(320, 180)
    sof = real.index(b"\xff\xc0")
    huge = real[: sof + 5] + (30000).to_bytes(2, "big") * 2 + real[sof + 9 :]  # height, then width
    assert pictures.read_jpeg_size(real) == {"width": 320, "height": 180}
    assert pictures.read_jpeg_size(huge) == {"width": 30000, "height": 30000}
    decoded = []
    monkeypatch.setattr(pictures.cv2, "imdecode", lambda *args: decoded.append(args) or None)
    for sent in (huge, b"\xff\xd8" + b"\x00" * 64, b"\xff\xd8\xff\xe0\x00\x00"):
        assert pictures.read_browser_picture(as_base64(sent)) is None
    assert decoded == [], "cv2 never saw them"


def test_a_huge_size_hidden_where_libjpeg_reads_the_header_another_way_is_dropped(monkeypatch):
    from dayanpi.focus import pictures

    real = make_jpeg(320, 180)
    sof = real.index(b"\xff\xc0")
    small, rest = real[sof : sof + 19], real[sof + 19 :]
    huge = small[:5] + (30000).to_bytes(2, "big") * 2 + small[9:]
    comment = b"\xff\xfe\x00\x15"  # a COM segment around the small SOF, so libjpeg skips it
    crafted = [
        real[:sof] + b"\xff\xd0\x00\x19" + huge + comment + small + rest,  # RST0 has no length: libjpeg reads the huge one
        real[:sof] + b"\xff\x01\x00\x19" + huge + comment + small + rest,  # TEM, the same way
        real[:sof] + b"\xff\xfe\x00\x02\x00\x00" + huge + rest,  # stray bytes before a marker, which libjpeg skips
        real[:sof] + b"\xff\xfe\x00\x00" + huge + rest,  # a length under 2
        real[:sof] + small + huge + rest,  # two sizes
        real[:sof] + small,  # never gets to the scan
    ]
    decoded = []
    monkeypatch.setattr(pictures.cv2, "imdecode", lambda *args: decoded.append(args) or None)
    for sent in crafted:
        assert pictures.read_jpeg_size(sent) is None
        assert pictures.read_browser_picture(as_base64(sent)) is None
    assert decoded == [], "cv2 never saw them"


def test_pictures_never_touch_the_disk(tmp_path, monkeypatch):
    sam = add_member("sam")
    desk = desk_of(sam)
    client = let_in(stranger(), sam)
    client.post("/api/sharing", json={"video": True})
    read_with_picture(client, as_base64(make_jpeg()), person=0.9)
    read_with_picture(client, as_base64(make_jpeg()), person=0.9)  # working now, so the log has its state line
    before = list_files(tmp_path)
    desk.browser._tokens = 2
    picture = make_jpeg(320, 180)
    read_with_picture(client, as_base64(picture))
    put_on_the_phone(monkeypatch, desk)
    assert let_in(stranger(), find_owner()).get("/api/people/sam/picture").status_code == 200
    after = list_files(tmp_path)
    assert after == before, "a picture changed the data folder"
    for name in after:
        content = (tmp_path / name).read_bytes()
        assert picture not in content and as_base64(picture).encode() not in content, f"the picture ended up in {name}"


def test_my_tile_is_off_until_i_turn_video_on(monkeypatch):
    mine = use_owner_desk(monkeypatch)
    monkeypatch.setattr(app.stream, "latest_frame", lambda: make_jpeg(640, 480))
    put_on_the_phone(monkeypatch, mine)
    app.take_owner_picture(time.time())
    assert mine.picture is None, "my tile starts off"
    mine.sharing.update({"video": True})
    app.take_owner_picture(time.time())
    import cv2
    import numpy as np

    shrunk = cv2.imdecode(np.frombuffer(mine.picture["jpeg"], dtype=np.uint8), cv2.IMREAD_COLOR)
    assert shrunk.shape[:2] == (360, 640), "the seat's size, cut to 16:9 on the Pi"
    mine.camera_source.set("browser")
    mine.picture = None
    app.take_owner_picture(time.time())
    assert mine.picture is None, "on the browser's camera, the browser sends it instead"


def pick_my_pictures(monkeypatch, source, picture):
    """My desk tracked by `source`, my picture from `picture` (None: not picked), video on, on the phone at the desk,
    and a Pi camera with a 640x480 frame."""
    mine = use_owner_desk(monkeypatch)
    mine.camera_source.update({"source": source, "picture": picture})
    mine.sharing.update({"video": True})
    monkeypatch.setattr(app.stream, "latest_frame", lambda: make_jpeg(640, 480), raising=False)
    put_on_the_phone(monkeypatch, mine)
    return mine


def send_picture_only(client, picture: str | None):
    return client.post("/api/track/picture", json={"picture": picture})


def test_only_my_desk_picks_where_its_picture_comes_from_and_it_starts_out_following_the_checks():
    with open_client() as client, open_client("member") as member:
        first = client.get("/api/focus").json()["picture_source"]
        tracked_by_browser = client.post("/api/track/source", json={"source": "browser"}).json()
        picked = client.post("/api/track/source", json={"picture": "pi"}).json()
        back_to_the_pi = client.post("/api/track/source", json={"source": "pi"}).json()
        member_pick = member.post("/api/track/source", json={"picture": "browser"})
        member_status = member.get("/api/focus").json()
    assert first == "pi", "until I pick, the picture comes from wherever my checks do"
    assert tracked_by_browser == {"source": "browser", "picture": "browser", "pi_camera": "front"}
    assert (picked, back_to_the_pi) == ({"source": "browser", "picture": "pi", "pi_camera": "front"}, {"source": "pi", "picture": "pi", "pi_camera": "front"})
    assert (member_pick.status_code, member_pick.json()) == (403, {"detail": "your picture is always your browser's"})
    assert (member_status["camera_source"], member_status["picture_source"]) == ("browser", "browser")


def test_tracked_by_the_pi_with_the_pi_picture_my_tile_is_the_pi_cameras(monkeypatch):
    mine = pick_my_pictures(monkeypatch, "pi", None)
    app.take_owner_picture(time.time())
    assert mine.picture is not None and mine.picture["jpeg"] != make_jpeg(640, 480), "the Pi's frame, shrunk"
    reply = send_picture_only(let_in(stranger(), find_owner()), as_base64(make_jpeg()))
    assert (reply.status_code, reply.json()) == (409, {"detail": "this desk's picture comes from the Pi's camera"})


def test_tracked_by_the_pi_with_the_browser_picture_the_browser_sends_it_alone(monkeypatch):
    mine = pick_my_pictures(monkeypatch, "pi", "browser")
    client = let_in(stranger(), find_owner())
    app.take_owner_picture(time.time())
    assert mine.picture is None, "the Pi camera leaves my tile to the browser"
    asked = send_picture_only(client, None)
    assert (asked.status_code, asked.json()) == (200, {"state": "phone", "send_picture": True})
    assert send_picture_only(client, as_base64(make_jpeg())).json()["send_picture"] is True
    served = client.get(f"/api/people/{find_owner().username}/picture")
    assert (served.status_code, served.content) == (200, make_jpeg())
    send_picture_only(client, as_base64(make_jpeg(641, 360)))
    assert mine.picture is None, "checked like the reading's: too big is dropped, and the old one with it"
    assert client.post("/api/track/reading", json={"person": 0.9, "phone": 0, "elapsed_ms": 1}).status_code == 409, "the Pi tracks"

    real = mine.tracker.status
    monkeypatch.setattr(mine.tracker, "status", lambda now: {**real(now), "state": "away", "last_check": {"at": now}})
    away = send_picture_only(client, as_base64(make_jpeg()))
    assert (away.json(), mine.picture) == ({"state": "away", "send_picture": False}, None), "no picture while I'm away"


def test_tracked_by_the_browser_with_the_pi_picture_the_pi_camera_still_takes_it(monkeypatch):
    mine = pick_my_pictures(monkeypatch, "browser", "pi")
    client = let_in(stranger(), find_owner())
    app.take_owner_picture(time.time())
    tile = mine.picture
    assert tile is not None, "the Pi's cameras take my picture while the browser tracks me"
    reading = client.post("/api/track/reading", json={"person": 0.9, "phone": 0, "elapsed_ms": 1, "picture": as_base64(make_jpeg())})
    assert (reading.status_code, reading.json()["send_picture"]) == (200, False)
    assert mine.picture == tile, "a reading neither replaces nor drops the Pi's picture"
    assert send_picture_only(client, as_base64(make_jpeg())).status_code == 409


def test_tracked_by_the_browser_with_the_browser_picture_the_reading_carries_it(monkeypatch):
    mine = pick_my_pictures(monkeypatch, "browser", None)
    client = let_in(stranger(), find_owner())
    app.take_owner_picture(time.time())
    assert mine.picture is None
    reading = client.post("/api/track/reading", json={"person": 0.9, "phone": 0, "elapsed_ms": 1})
    assert reading.json()["send_picture"] is True


class FakeSideCamera:
    """The side camera: its own frame, and how long ago it came in (None: never)."""

    def __init__(self, age_s: float | None, jpeg: bytes = b"side") -> None:
        self.age_s = age_s
        self.jpeg = jpeg

    def frame_age_s(self) -> float | None:
        return self.age_s

    def latest_frame(self) -> bytes:
        return self.jpeg


def test_my_tile_comes_from_the_pi_camera_i_pick_and_falls_back_to_the_front(monkeypatch):
    mine = pick_my_pictures(monkeypatch, "pi", None)
    monkeypatch.setattr(app, "shrink_frame", lambda jpeg: jpeg)  # the same shrink either way; this shows which camera
    monkeypatch.setattr(app.stream, "latest_frame", lambda: b"front", raising=False)
    side = FakeSideCamera(age_s=0.4)
    monkeypatch.setattr(app, "side_stream", side)

    def take_tile() -> bytes:
        app.take_owner_picture(time.time())
        return mine.picture["jpeg"]

    assert take_tile() == b"front", "front is the default"
    mine.camera_source.update({"pi_camera": "side"})
    status = app.build_desk_status(mine, time.time())
    assert (take_tile(), status["pi_camera"], status["side_camera_running"]) == (b"side", "side", True)
    side.age_s = 10.0
    assert (take_tile(), app.build_desk_status(mine, time.time())["side_camera_running"]) == (b"front", False), "dropped out"
    side.age_s = None
    assert take_tile() == b"front", "never sent a frame"
    monkeypatch.setattr(app, "side_stream", None)
    assert (take_tile(), app.build_desk_status(mine, time.time())["side_camera_running"]) == (b"front", False), "not both"


def test_the_side_cameras_tile_is_shrunk_like_the_fronts(monkeypatch):
    mine = pick_my_pictures(monkeypatch, "pi", None)
    mine.camera_source.update({"pi_camera": "side"})
    monkeypatch.setattr(app, "side_stream", FakeSideCamera(age_s=0.4, jpeg=make_jpeg(768, 432)))
    app.take_owner_picture(time.time())
    import cv2
    import numpy as np

    assert cv2.imdecode(np.frombuffer(mine.picture["jpeg"], dtype=np.uint8), cv2.IMREAD_COLOR).shape[:2] == (360, 640)


def test_only_i_pick_front_or_side_and_it_survives_a_restart():
    with open_client() as client, open_client("member") as member:
        picked = client.post("/api/track/source", json={"pi_camera": "side"}).json()
        status = client.get("/api/focus").json()
        wrong = client.post("/api/track/source", json={"pi_camera": "top"})
        member_pick = member.post("/api/track/source", json={"pi_camera": "side"})
    assert picked == {"source": "pi", "picture": "pi", "pi_camera": "side"}
    assert (status["pi_camera"], status["side_camera_running"]) == ("side", False), "no side camera in the tests"
    assert wrong.status_code == 422
    assert (member_pick.status_code, member_pick.json()) == (403, {"detail": "your picture is always your browser's"})
    saved = CameraSourceSetting(desk_of(find_owner()).days_dir.parent / CAMERA_SOURCE_FILE)
    assert saved.pi_camera == "side", "read back from the disk, as a restart would"


def test_a_member_cant_send_a_picture_on_its_own():
    sam = add_member("sam")
    desk_of(sam).sharing.update({"video": True})
    reply = send_picture_only(let_in(stranger(), sam), as_base64(make_jpeg()))
    assert reply.status_code == 403 and desk_of(sam).picture is None, "a member's picture rides on their readings"


def run_producer_once(seconds: float = 1.3) -> None:
    """The real once-a-second loop, for about one tick: the pictures, the statuses and the room, as on the Pi."""

    async def run():
        task = asyncio.create_task(app.snapshot_producer())
        await asyncio.sleep(seconds)
        task.cancel()

    import asyncio

    asyncio.run(run())


def test_my_tile_reaches_the_room_stream_end_to_end(real_server, monkeypatch):
    mine = use_owner_desk(monkeypatch)
    owner = find_owner()
    mine.sharing.update({"video": True})
    monkeypatch.setattr(app.stream, "latest_frame", lambda: make_jpeg(640, 480), raising=False)  # the test server's camera has none
    put_on_the_phone(monkeypatch, mine)
    run_producer_once()
    with httpx.stream("GET", real_server + "/api/stream", headers=session_header(owner), timeout=3) as response:
        [event] = read_events(response, 1)
    [seat] = [seat for seat in event["room"]["seats"] if seat["username"] == owner.username]
    assert seat["picture"] is not None, seat
    picture = httpx.get(real_server + f"/api/people/{owner.username}/picture?at={seat['picture']['at']}", headers=session_header(owner), timeout=3)
    assert (picture.status_code, picture.headers["content-type"]) == (200, "image/jpeg")


def test_a_browser_picture_reaches_the_room_stream_end_to_end(real_server):
    sam = add_member("sam")
    desk = desk_of(sam)
    desk_of(find_owner())  # the viewer's own desk, or the stream only pings
    headers = {**session_header(sam), "Content-Type": "application/json"}
    httpx.post(real_server + "/api/sharing", headers=headers, json={"video": True}, timeout=3)
    for _ in range(2):
        reply = httpx.post(real_server + "/api/track/reading", headers=headers, json={"person": 0.9, "phone": 0, "elapsed_ms": 100, "picture": as_base64(make_jpeg())}, timeout=3)
        assert reply.status_code == 200, reply.text
    assert reply.json()["send_picture"] is True and desk.picture is not None
    run_producer_once()
    with httpx.stream("GET", real_server + "/api/stream", headers=session_header(find_owner()), timeout=3) as response:
        [event] = read_events(response, 1)
    [seat] = [seat for seat in event["room"]["seats"] if seat["username"] == "sam"]
    assert seat["picture"] is not None, seat
