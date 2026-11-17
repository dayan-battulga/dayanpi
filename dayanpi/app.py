import asyncio
import json
import logging
import os
import re
import threading
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketClose
from pydantic import BaseModel, Field, StrictBool, StringConstraints

from typing import Annotated, Literal

from dayanpi.auth import routes as auth_routes
from dayanpi.auth.accounts import SESSION_REFRESH_S
from dayanpi.hardware import collector
from dayanpi.focus import days
from dayanpi.focus import worker as focus_worker
from dayanpi.hardware.camera import CameraStream, create_side_stream, create_stream
from dayanpi.focus.tracker import FocusLog, FocusTracker, FocusUpdate, find_focus_log_dir, format_day
from dayanpi.focus.coach import TodoCoach, read_bedtime
from dayanpi.focus.mac_tracking import MacTrackingSetting, find_mac_tracking_path
from dayanpi.focus.todos import TEXT_MAX, TodoList, find_todo_path
from dayanpi.focus.worker import FocusWorker
from dayanpi.hardware.llm import OllamaClient, read_llm_model
from dayanpi.hardware.voice import VoiceAnnouncer
from dayanpi.paths import STATIC_DIR

# uvicorn only configures its own loggers; without this the app's INFO lines
# ("focus tracker running", "voice off, would say ...") never reach journalctl.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

FOCUS_LOG_DIR = find_focus_log_dir()
DAYS_DIR = days.find_days_dir()

FRAME_BOUNDARY = "frame"
FRAME_TIMEOUT_S = 5.0
MAX_CONSECUTIVE_TIMEOUTS = 3
SNAPSHOT_INTERVAL_S = 1.0
VIDEO_MAX_CONCURRENT = 2
STREAM_MAX_CONCURRENT = 5  # per account
FEED_SESSION_CHECK_S = 1.0  # an open camera feed checks its viewer is still signed in this often
AFTER_MIDNIGHT_S = 5.0  # the day pages get written this long after local midnight
# The biggest write body. FastAPI reads a whole body before any max_length runs, and the sign-in is public.
MAX_BODY_BYTES = 64 * 1024

logger = logging.getLogger(__name__)

# Only used to make the owner account when accounts.db has no users (the first start, or after it's deleted).
AUTH_USER = os.environ.get("DAYANPI_USER", "")
AUTH_PASSWORD = os.environ.get("DAYANPI_PASSWORD", "")

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PAGES = {"/login", "/api/health"}
PUBLIC_WRITES = {"/api/login", "/api/join", "/api/logout"}
JOIN_PAGE = re.compile(r"/join/[A-Za-z0-9_-]{1,64}")
CONTENT_LENGTH = re.compile(r"[0-9]{1,9}")
# A join link, in a path or inside a query (a stray "/" on the link turns it into /login?next=%2Fjoin%2F...).
JOIN_LINK = re.compile(r"(/|%2F)join(/|%2F)[^?&\s]*", re.IGNORECASE)
# Members can read the owner's data but not change it. These writes are their own account things; every
# other write is the owner's, so a new write route stays owner-only until it's added here.
MEMBER_WRITES = re.compile(r"PATCH /api/me|POST /api/me/password|POST /api/tokens|DELETE /api/tokens/[0-9]+")
OWNER_READS = {"/api/stats", "/api/invites", "/api/accounts"}
INDEX_PAGE = STATIC_DIR / "index.html"

sampler = collector.RateSampler("wlan0")
stream = create_stream()
side_stream = create_side_stream()
latest_snapshot: dict | None = None
focus_log = FocusLog(FOCUS_LOG_DIR)
tracker = FocusTracker(focus_log, started_at=time.time())
todos = TodoList(find_todo_path(), focus_log)
mac_tracking = MacTrackingSetting(find_mac_tracking_path())
worker: FocusWorker | None = None
voice = VoiceAnnouncer()
LLM_MODEL = read_llm_model()
coach = TodoCoach(todos, read_bedtime(), None if LLM_MODEL is None else OllamaClient(LLM_MODEL))

_video_slots = threading.BoundedSemaphore(VIDEO_MAX_CONCURRENT)
_side_video_slots = threading.BoundedSemaphore(VIDEO_MAX_CONCURRENT)
# One pool per account, so a member's open tabs can't use up the owner's.
_stream_slots: defaultdict[int, threading.BoundedSemaphore] = defaultdict(
    lambda: threading.BoundedSemaphore(STREAM_MAX_CONCURRENT)
)


class InviteCodeFilter(logging.Filter):
    """uvicorn's access log prints every path with its query, and a join link carries a live invite code."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > 2 and isinstance(args[2], str):
            record.args = args[:2] + (JOIN_LINK.sub(r"\1join\2…", args[2]),) + args[3:]
        return True


logging.getLogger("uvicorn.access").addFilter(InviteCodeFilter())


def stamp_age(event: dict | None, now: float) -> dict | None:
    """The page hides boxes and toasts after a few seconds, so it needs their age, not the Pi's clock."""
    stamped = None if event is None else {**event, "age_s": round(now - event["at"], 1)}
    return stamped


def build_focus_status() -> dict:
    """The focus status for the API and the stats stream."""
    now = time.time()
    status = tracker.status(now)
    status["enabled"] = worker is not None and worker.running
    status["side_camera"] = side_stream is not None
    status["overlay"] = stamp_age(None if worker is None else worker.last_overlay, now)
    status["side_overlay"] = stamp_age(None if worker is None else worker.last_side_overlay, now)
    status["gesture"] = stamp_age(None if worker is None else worker.last_gesture, now)
    status["voice"] = {"enabled": voice.enabled, "backend": voice.backend, "problem": voice.problem}
    status["todos"] = todos.snapshot(now)
    status["mac_tracking"] = mac_tracking.enabled
    return status


def find_camera_access(request: Request) -> str:
    """"open" when this request may have the full feeds: the owner's session, and with DAYANPI_TAILSCALE_LOGIN
    set, from the owner's own Tailscale devices. Otherwise why not: "owner_only" or "tailscale_only"."""
    viewer = auth_routes.read_viewer(request)
    if viewer.user.role != "owner" or viewer.session is None:
        access = "owner_only"
    elif auth_routes.TAILSCALE_LOGIN and not auth_routes.is_from_my_devices(request):
        access = "tailscale_only"
    else:
        access = "open"
    return access


def shape_focus(focus: dict, access: str) -> dict:
    """One viewer's copy of the focus status. The boxes come off the camera, so they go wherever the feed can't."""
    shaped = {**focus, "camera_access": access}
    if access != "open":
        shaped["overlay"] = None
        shaped["side_overlay"] = None
    return shaped


def shape_snapshot(snapshot: dict, request: Request) -> dict:
    """The owner gets the Pi's numbers too; a member only the focus status."""
    focus = shape_focus(snapshot["focus"], find_camera_access(request))
    shaped = {**snapshot, "focus": focus} if auth_routes.read_viewer(request).user.role == "owner" else {"focus": focus}
    return shaped


def handle_focus_update(update: FocusUpdate, now: float) -> None:
    """Runs on the worker thread after every check. Callouts go to the journal, and to the speaker when they speak."""
    for callout in update.callouts:
        logger.info("focus callout %s: %s", callout.name, callout.text)
        if callout.speak:
            voice.say(callout.text)
    todos.track(update.state == "working", now)


def say_todos(now: float) -> dict:
    """Speaks the coach's message and returns which kind it was, for the gesture's log line."""
    message = coach.pick(now)
    logger.info("peace sign: speaking the %s message", message.source)
    voice.say(message.text)
    return {"spoken": message.source}


# What each hand sign does when it fires. Its finger rule lives in vision/gestures.py (HAND_SIGNS).
# An action returns extra fields for the sign's gesture line in the focus log.
SIGN_ACTIONS = {"peace": say_todos}


def handle_gesture(name: str, now: float) -> None:
    """Runs on the worker thread when a hand sign fires."""
    details = SIGN_ACTIONS[name](now) if name in SIGN_ACTIONS else {}
    tracker.record_gesture(name, now, **details)


def start_focus_worker() -> FocusWorker | None:
    started = None
    scanner = focus_worker.build_scanner()
    if scanner is not None:
        now = time.time()
        restored = tracker.restore(focus_log.read_day(format_day(now)), now)
        if restored:
            logger.info("focus tracker restored %s events from today's log", restored)
        started = FocusWorker(
            stream,
            scanner,
            tracker,
            on_update=handle_focus_update,
            on_gesture=handle_gesture,
            wait_for_clock_first=True,
            side_stream=side_stream,
            hand_scanner=focus_worker.build_hand_scanner(),
        )
        started.start()
        logger.info("focus tracker running; log in %s", FOCUS_LOG_DIR)
    return started


async def snapshot_producer() -> None:
    """One owner of the sampler; SSE clients only read latest_snapshot."""
    global latest_snapshot
    while True:
        try:
            snapshot = collector.snapshot(sampler)
            snapshot["focus"] = build_focus_status()
            latest_snapshot = snapshot
        except Exception:
            logger.exception("snapshot producer failed")
        await asyncio.sleep(SNAPSHOT_INTERVAL_S)


async def day_page_writer() -> None:
    """Writes the missing day pages at startup, then again just after each local midnight.

    It waits for the network clock first, like the focus worker: before that, "today" can
    be a day that's already over.
    """
    await asyncio.to_thread(focus_worker.wait_for_clock)
    while True:
        try:
            written = await asyncio.to_thread(days.write_missing_pages, focus_log, DAYS_DIR, time.time())
            if written:
                logger.info("day pages written: %s", ", ".join(written))
        except Exception:
            logger.exception("day pages failed")
        await asyncio.sleep(days.find_seconds_until_midnight(time.time()) + AFTER_MIDNIGHT_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker
    if not AUTH_USER or not AUTH_PASSWORD:
        raise RuntimeError(
            "DAYANPI_USER and DAYANPI_PASSWORD must be set "
            "(e.g. via EnvironmentFile=/etc/dayanpi.env)"
        )
    if auth_routes.accounts.seed_owner(AUTH_USER, AUTH_PASSWORD, time.time()):
        logger.info("made the owner account from DAYANPI_USER and DAYANPI_PASSWORD")
    if auth_routes.TAILSCALE_LOGIN:
        logger.info("camera locked to Tailscale login %s", auth_routes.TAILSCALE_LOGIN)
    else:
        logger.warning("camera not locked to Tailscale, don't turn on Funnel")
    sampler.sample()
    if not mac_tracking.enabled:
        tracker.set_mac_tracking(False, time.time())
        logger.info("Mac tracking is paused (switched off on the dashboard)")
    stream.start()
    if side_stream is not None:
        side_stream.start()
    voice.start()
    worker = start_focus_worker()
    if coach.llm is not None:
        coach.start()
        logger.info("peace sign: writing messages ahead with %s through Ollama", coach.llm.model)
    else:
        logger.info("peace sign: template messages (DAYANPI_LLM_MODEL isn't set)")
    producer = asyncio.create_task(snapshot_producer(), name="snapshot-producer")
    day_pages = asyncio.create_task(day_page_writer(), name="day-page-writer")
    yield
    for task in (producer, day_pages):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    if worker is not None:
        worker.stop()
        worker = None
    coach.stop()
    todos.save(time.time())
    voice.stop()
    stream.stop()
    if side_stream is not None:
        side_stream.stop()


app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class WebSocketGate:
    """Closes every WebSocket handshake. The session middleware only sees HTTP, so one would reach the routes
    unchecked, and StaticFiles asserts on it: a 500 and a traceback in the journal per stranger's try."""

    def __init__(self, inner) -> None:
        self.inner = inner

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "websocket":
            await WebSocketClose(code=1008)(scope, receive, send)
        else:
            await self.inner(scope, receive, send)


app.add_middleware(WebSocketGate)


@app.exception_handler(RequestValidationError)
async def refuse_invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
    """Where and what was wrong, never the value sent."""
    # FastAPI's own 422 repeats each bad value, a password too, and can't encode a lone surrogate or NaN: that
    # 422 turns into a 500 whose traceback writes the value into the journal.
    problems = [{"loc": problem["loc"], "msg": problem["msg"], "type": problem["type"]} for problem in error.errors()]
    response = JSONResponse({"detail": problems}, status_code=422)
    return response


app.include_router(auth_routes.router)


def read_media_type(request: Request) -> str:
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    return media_type


def is_body_small(request: Request) -> bool:
    """uvicorn ends a body at its Content-Length, so a write must send one under the cap. A chunked body has
    none and could run on for as long as the sender likes."""
    length = request.headers.get("content-length", "")
    small = "transfer-encoding" not in request.headers and CONTENT_LENGTH.fullmatch(length) is not None and int(length) <= MAX_BODY_BYTES
    return small


def is_public(method: str, path: str) -> bool:
    """The sign-in and join pages, what they load, and the routes they call."""
    if method in ("GET", "HEAD"):
        is_asset = path.startswith("/assets/") and ".." not in path and "\\" not in path
        public = path in PUBLIC_PAGES or JOIN_PAGE.fullmatch(path) is not None or is_asset
    else:
        public = method == "POST" and path in PUBLIC_WRITES
    return public


def is_member_allowed(method: str, path: str) -> bool:
    allowed = MEMBER_WRITES.fullmatch(f"{method} {path}") is not None if method not in READ_METHODS else path not in OWNER_READS
    return allowed


def refuse_stranger(request: Request, path: str) -> Response:
    """No sign-in: the API, the feeds and a Mac token used anywhere but /api/mac/ get a 401, a page the sign-in page."""
    is_page = request.method in ("GET", "HEAD") and auth_routes.read_bearer(request) is None
    if is_page and not path.startswith(("/api/", "/video")):
        query = request.scope["query_string"].decode("latin-1")
        response = RedirectResponse("/login?next=" + quote(path + (f"?{query}" if query else ""), safe=""), status_code=303)
    else:
        response = JSONResponse({"detail": "sign in first"}, status_code=status.HTTP_401_UNAUTHORIZED)
    return response


async def guard_request(request: Request, call_next) -> Response:
    # scope["path"] is what the router matches; request.url.path re-splits it, so a %3F could make the two differ.
    path = request.scope["path"]
    now = time.time()
    if request.method not in READ_METHODS and read_media_type(request) != "application/json":
        # A form or a text/plain post from another site can't send application/json without a CORS preflight.
        response = JSONResponse({"detail": "send JSON"}, status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    elif request.method not in READ_METHODS and not is_body_small(request):
        response = JSONResponse({"detail": "too big"}, status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    elif is_public(request.method, path):
        response = await call_next(request)
    elif (viewer := auth_routes.find_viewer(request, now)) is None:
        response = refuse_stranger(request, path)
    elif viewer.user.role != "owner" and not is_member_allowed(request.method, path):
        response = JSONResponse({"detail": "only the owner can do that"}, status_code=status.HTTP_403_FORBIDDEN)
    else:
        request.state.viewer = viewer
        response = await call_next(request)
        session = viewer.session
        if session is not None and now - session.extended_at > SESSION_REFRESH_S:
            auth_routes.accounts.extend_session(session.token_hash, now)
            auth_routes.set_session_cookie(response, request.cookies[auth_routes.SESSION_COOKIE])
    return response


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    # Covers API routes and StaticFiles — app dependencies don't apply to mounts.
    response = await guard_request(request, call_next)
    # A signed-in browser sends its cookie inside frames too, so another page could frame the dashboard.
    response.headers["X-Frame-Options"] = "DENY"
    # The /join/<code> page must not hand its code to anything it loads or links to.
    response.headers["Referrer-Policy"] = "no-referrer"
    # Without it a browser can keep last week's focus.js against today's index.html after a git pull.
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


def frame_generator(camera: CameraStream, token: str) -> Iterator[bytes]:
    """Ends once the viewer's session is gone, like the stats stream: signed out, or ended by a password change."""
    last_id = -1
    consecutive_timeouts = 0
    checked_at = time.monotonic()

    while True:
        if time.monotonic() - checked_at >= FEED_SESSION_CHECK_S:
            if auth_routes.accounts.find_session(token, time.time()) is None:
                return
            checked_at = time.monotonic()
        result = camera.frame_after(last_id, timeout=FRAME_TIMEOUT_S)
        if result is None:
            consecutive_timeouts += 1
            if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                return
            continue

        consecutive_timeouts = 0
        jpeg, last_id = result
        yield (
            f"--{FRAME_BOUNDARY}\r\n"
            f"Content-Type: image/jpeg\r\n"
            f"Content-Length: {len(jpeg)}\r\n"
            f"\r\n"
        ).encode("ascii") + jpeg + b"\r\n"


async def event_stream(request: Request) -> AsyncIterator[bytes]:
    """Each viewer gets their own copy of the shared snapshot, and the stream ends once their session is gone."""
    token = request.cookies.get(auth_routes.SESSION_COOKIE, "")
    try:
        yield b"retry: 5000\n\n"
        while True:
            if await request.is_disconnected():
                break
            # Signed out, or the account removed: no more live data from this second on.
            if auth_routes.accounts.find_session(token, time.time()) is None:
                break

            snapshot = latest_snapshot
            if snapshot is not None:
                yield f"data: {json.dumps(shape_snapshot(snapshot, request))}\n\n".encode("utf-8")
            else:
                yield b": ping\n\n"

            await asyncio.sleep(SNAPSHOT_INTERVAL_S)
    finally:
        logger.info("SSE client disconnected")


@app.get("/api/stats")
def stats(request: Request):
    """Owner only (OWNER_READS)."""
    return shape_snapshot(latest_snapshot, request) if latest_snapshot is not None else {}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/focus")
def focus_now(request: Request):
    status = shape_focus(build_focus_status(), find_camera_access(request))
    status["segments"] = tracker.segments()
    return status


TodoText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TEXT_MAX)]


class TodoNew(BaseModel):
    text: TodoText


class TodoChange(BaseModel):
    text: TodoText | None = None
    done: bool | None = None
    current: bool | None = None


def build_today_page(now: float) -> str:
    today = format_day(now)
    page = days.build_day_page(focus_log.read_day(today), today)
    return page


@app.get("/api/days")
def month_days(month: Annotated[str, Query(pattern=days.MONTH_PATTERN)]):
    """A month's numbers for the calendar, one entry per day with a page. Today's comes live from the log."""
    now = time.time()
    today = format_day(now)
    found = days.read_month(DAYS_DIR, month)
    if today.startswith(month + "-"):
        found[today] = days.read_page_totals(build_today_page(now))
    return {"month": month, "today": today, "days": found}


@app.get("/api/apps")
def list_apps(range: Annotated[Literal["today", "week"], Query()] = "today"):
    """Time per Mac app for the Apps card, biggest first: the top 8, then the rest as "Other apps"."""
    apps = days.build_apps_chart(focus_log, time.time(), range)
    return {"range": range, "apps": apps}


@app.get("/api/days/{day}")
def day_page(day: Annotated[str, PathParam(pattern=days.DAY_PATTERN)]):
    """One day's page as markdown. The pattern keeps the name to digits and dashes, so it can only be a file in data/days."""
    now = time.time()
    today = format_day(now)
    path = DAYS_DIR / f"{day}.md"
    if day == today:
        page = build_today_page(now)
    elif path.is_file():
        page = path.read_text(encoding="utf-8")
    else:
        raise HTTPException(status_code=404, detail="no page for that day")
    return {"day": day, "today": day == today, "markdown": page}


@app.get("/api/todos")
def list_todos():
    return todos.snapshot(time.time())


@app.post("/api/todos")
def add_todo(new: TodoNew):
    now = time.time()
    item = todos.add(new.text, now)
    return {"status": "ok", "item": item, "todos": todos.snapshot(now)}


@app.patch("/api/todos/{item_id}")
def change_todo(item_id: str, change: TodoChange):
    now = time.time()
    if not todos.change(item_id, now, text=change.text, done=change.done, current=change.current):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such to-do")
    return {"status": "ok", "todos": todos.snapshot(now)}


@app.delete("/api/todos/{item_id}")
def delete_todo(item_id: str):
    now = time.time()
    if not todos.delete(item_id, now):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such to-do")
    return {"status": "ok", "todos": todos.snapshot(now)}


# A plain host name like youtube.com: lowercase labels of letters, digits and inner hyphens. The Mac helper
# makes the same check, so a full URL, a path or a page title can't get through either end.
SITE_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
SITE_MAX = 253


class AppReport(BaseModel):
    app: str = Field(min_length=1, max_length=100)
    site: Annotated[str, StringConstraints(max_length=SITE_MAX, pattern=SITE_PATTERN)] | None = None


class MacTrackingChange(BaseModel):
    enabled: StrictBool


@app.post("/api/mac/app")
def mac_app(report: AppReport):
    """While Mac tracking is off the tracker drops the report; "enabled" tells the helper to stop asking."""
    changed = tracker.record_app(report.app.strip(), time.time(), site=report.site)
    return {"status": "ok", "changed": changed, "enabled": mac_tracking.enabled}


@app.get("/api/mac/tracking")
def get_mac_tracking():
    return {"enabled": mac_tracking.enabled}


@app.post("/api/mac/tracking")
def set_mac_tracking(change: MacTrackingChange):
    if mac_tracking.set(change.enabled):
        tracker.set_mac_tracking(change.enabled, time.time())
    return {"enabled": mac_tracking.enabled}


class SlotResponse(StreamingResponse):
    """A stream on a capped route, which gives its slot back the moment it ends, however it ends.

    A finally inside the generator can't do this. When a viewer hangs up the generator just stops
    being read, so its finally waits for the garbage collector, and until then the next viewer
    gets a 503. If they hang up before it starts, the finally never runs at all.
    """

    def __init__(self, content, slots: threading.BoundedSemaphore, **options) -> None:
        super().__init__(content, **options)
        self._slots = slots

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._slots.release()


@app.get("/api/stream")
async def api_stream(request: Request):
    slots = _stream_slots[auth_routes.read_viewer(request).user.id]
    if not slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many stream connections",
        )

    return SlotResponse(
        event_stream(request),
        slots,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def stream_video(camera: CameraStream, slots: threading.BoundedSemaphore, request: Request) -> StreamingResponse:
    if not slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many video connections",
        )

    response = SlotResponse(
        frame_generator(camera, request.cookies.get(auth_routes.SESSION_COOKIE, "")),
        slots,
        media_type=f"multipart/x-mixed-replace; boundary={FRAME_BOUNDARY}",
    )
    return response


def require_camera(request: Request) -> None:
    """The same plain 404 as a route that doesn't exist, for a member, a stranger's header or none at all."""
    if find_camera_access(request) != "open":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@app.get("/video")
def video(request: Request):
    require_camera(request)
    return stream_video(stream, _video_slots, request)


@app.get("/video/side")
def side_video(request: Request):
    require_camera(request)
    if side_stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No side camera")
    return stream_video(side_stream, _side_video_slots, request)


@app.get("/login")
@app.get("/join/{code}")
@app.get("/settings")
def page():
    """The page's own routes; the page picks what to show from the address. "/" comes from the static mount."""
    return FileResponse(INDEX_PAGE)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
