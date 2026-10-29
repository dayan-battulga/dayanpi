import asyncio
import base64
import json
import logging
import os
import secrets
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from typing import Literal

from dayanpi.hardware import collector
from dayanpi.focus import worker as focus_worker
from dayanpi.hardware.camera import create_stream
from dayanpi.hardware.drivetrain import CommandTimer, DriveTrain
from dayanpi.focus.tracker import FocusLog, FocusTracker, FocusUpdate, find_focus_log_dir, format_day
from dayanpi.focus.worker import FocusWorker
from dayanpi.hardware.voice import VoiceAnnouncer
from dayanpi.paths import STATIC_DIR
from dayanpi.sign.controller import SignController
from dayanpi.sign.renderer import PanelOutput, PreviewOutput

# uvicorn only configures its own loggers; without this the app's INFO lines
# ("focus tracker running", "voice off, would say ...") never reach journalctl.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

FOCUS_LOG_DIR = find_focus_log_dir()

FRAME_BOUNDARY = "frame"
FRAME_TIMEOUT_S = 5.0
MAX_CONSECUTIVE_TIMEOUTS = 3
SNAPSHOT_INTERVAL_S = 1.0
VIDEO_MAX_CONCURRENT = 2
STREAM_MAX_CONCURRENT = 5
WATCHDOG_INTERVAL_S = 0.1
DRIVE_TIMEOUT_S = 0.5

logger = logging.getLogger(__name__)

AUTH_USER = os.environ.get("DAYANPI_USER", "")
AUTH_PASSWORD = os.environ.get("DAYANPI_PASSWORD", "")

sampler = collector.RateSampler("wlan0")
stream = create_stream()
latest_snapshot: dict | None = None
drive_train: DriveTrain | None = None
command_timer = CommandTimer(DRIVE_TIMEOUT_S)
focus_log = FocusLog(FOCUS_LOG_DIR)
tracker = FocusTracker(focus_log, started_at=time.time())
worker: FocusWorker | None = None
voice = VoiceAnnouncer()
SIGN_MODE = os.environ.get("DAYANPI_SIGN", "preview").strip().lower() or "preview"  # preview | panel | off
sign_preview = PreviewOutput()
sign_controller: SignController | None = None

_video_slots = threading.BoundedSemaphore(VIDEO_MAX_CONCURRENT)
_stream_slots = threading.BoundedSemaphore(STREAM_MAX_CONCURRENT)


def _authorized(request: Request) -> bool:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    username, sep, password = decoded.partition(":")
    if not sep:
        return False
    user_ok = secrets.compare_digest(
        username.encode("utf-8"),
        AUTH_USER.encode("utf-8"),
    )
    pass_ok = secrets.compare_digest(
        password.encode("utf-8"),
        AUTH_PASSWORD.encode("utf-8"),
    )
    return user_ok and pass_ok


def build_focus_status(sign_since_version: int | None = None) -> dict:
    """The focus status for the API and the stats stream.

    The sign preview PNG (about 8 KB) rides along only when the picture changed since
    sign_since_version; None means always include it.
    """
    now = time.time()
    status = tracker.status(now)
    status["enabled"] = worker is not None and worker.running
    overlay = None if worker is None else worker.last_overlay
    # The page hides boxes older than a few seconds, so it needs their age, not the Pi's clock.
    status["overlay"] = None if overlay is None else {**overlay, "age_s": round(now - overlay["at"], 1)}
    status["voice"] = {"enabled": voice.enabled, "backend": voice.backend, "problem": voice.problem}
    version = sign_preview.version if sign_controller is not None else None
    status["sign"] = {"mode": SIGN_MODE, "page": None if sign_controller is None else sign_controller.page, "version": version}
    include_png = sign_controller is not None and (sign_since_version is None or version != sign_since_version)
    png = sign_preview.latest_png() if include_png else None
    if png is not None:
        status["sign_png"] = base64.b64encode(png).decode("ascii")
    return status


def start_sign() -> SignController | None:
    """The sign always renders for the website preview; the panels join in when DAYANPI_SIGN=panel."""
    started = None
    if SIGN_MODE != "off":
        outputs = [sign_preview]
        if SIGN_MODE == "panel":
            try:
                outputs.append(PanelOutput())
                logger.info("sign: driving the panels")
            except Exception:
                logger.exception("sign: panels unavailable, preview only (is Piomatter installed, see docs/MANUAL.md)")
        started = SignController(tracker, outputs)
        started.start()
    return started


def handle_focus_update(update: FocusUpdate, now: float) -> None:
    """Runs on the worker thread after every check. Callouts fan out to the speaker and the sign from here."""
    for callout in update.callouts:
        logger.info("focus callout %s: %s", callout.name, callout.text)
        if callout.speak:
            voice.say(callout.text)
        if sign_controller is not None:
            sign_controller.show_callout(callout)


def handle_gesture(name: str, now: float) -> None:
    """Runs on the worker thread when a held gesture fires."""
    tracker.record_gesture(name, now)
    if name == "toggle_block":
        active = tracker.toggle_block(now, source="gesture")
        voice.say("Block started." if active else "Block stopped.")
    elif sign_controller is not None and name in ("next_page", "previous_page"):
        sign_controller.flip_page(1 if name == "next_page" else -1)


def start_focus_worker() -> FocusWorker | None:
    started = None
    scanner = focus_worker.build_scanner()
    if scanner is not None:
        now = time.time()
        restored = tracker.restore(focus_log.read_day(format_day(now)), now)
        if restored:
            logger.info("focus tracker restored %s events from today's log", restored)
        started = FocusWorker(
            stream, scanner, tracker, on_update=handle_focus_update, on_gesture=handle_gesture, wait_for_clock_first=True
        )
        started.start()
        logger.info("focus tracker running; log in %s", FOCUS_LOG_DIR)
    return started


async def snapshot_producer() -> None:
    """One owner of the sampler; SSE clients only read latest_snapshot."""
    global latest_snapshot
    sent_sign_version = None
    while True:
        try:
            snapshot = collector.snapshot(sampler)
            snapshot["focus"] = build_focus_status(sign_since_version=sent_sign_version)
            sent_sign_version = snapshot["focus"]["sign"]["version"]
            latest_snapshot = snapshot
        except Exception:
            logger.exception("snapshot producer failed")
        await asyncio.sleep(SNAPSHOT_INTERVAL_S)


async def watch_drive_commands() -> None:
    """Stops the motors once the browser stops sending commands."""
    while True:
        try:
            if command_timer.is_stale():
                drive_train.stop()
        except Exception:
            logger.exception("drive watchdog failed")
        await asyncio.sleep(WATCHDOG_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global drive_train, worker, sign_controller
    if not AUTH_USER or not AUTH_PASSWORD:
        raise RuntimeError(
            "DAYANPI_USER and DAYANPI_PASSWORD must be set "
            "(e.g. via EnvironmentFile=/etc/dayanpi.env)"
        )
    sampler.sample()
    stream.start()
    voice.start()
    sign_controller = start_sign()
    worker = start_focus_worker()
    drive_train = None
    watchdog = None
    if SIGN_MODE == "panel":
        # The Matrix Bonnet uses the six motor pins (12, 13, 17, 22, 23, 27), so it's one or the other.
        logger.info("sign on the panels, so the motors stay off; /api/drive will return 503")
    else:
        try:
            drive_train = DriveTrain()
            watchdog = asyncio.create_task(watch_drive_commands(), name="drive-watchdog")
        except Exception:
            # Busy pins, no gpio permission, no lgpio/gpiozero: run the dashboard without motors.
            logger.exception("motors unavailable; /api/drive will return 503")
    producer = asyncio.create_task(snapshot_producer(), name="snapshot-producer")
    try:
        yield
    finally:
        if watchdog is not None:
            watchdog.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog
            drive_train.close()
    producer.cancel()
    with suppress(asyncio.CancelledError):
        await producer
    if worker is not None:
        worker.stop()
        worker = None
    if sign_controller is not None:
        sign_controller.stop()
        sign_controller = None
    voice.stop()
    stream.stop()


app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    # Covers API routes and StaticFiles — app dependencies don't apply to mounts.
    if not _authorized(request):
        return Response(
            content="Unauthorized",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": 'Basic realm="dayanpi"'},
            media_type="text/plain",
        )
    return await call_next(request)


def frame_generator() -> Iterator[bytes]:
    last_id = -1
    consecutive_timeouts = 0

    while True:
        result = stream.frame_after(last_id, timeout=FRAME_TIMEOUT_S)
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
    try:
        yield b"retry: 5000\n\n"
        while True:
            if await request.is_disconnected():
                break

            snapshot = latest_snapshot
            if snapshot is not None:
                yield f"data: {json.dumps(snapshot)}\n\n".encode("utf-8")
            else:
                yield b": ping\n\n"

            await asyncio.sleep(SNAPSHOT_INTERVAL_S)
    finally:
        _stream_slots.release()
        logger.info("SSE client disconnected")


@app.get("/api/stats")
def stats():
    return latest_snapshot if latest_snapshot is not None else {}


@app.get("/api/health")
def health():
    return {"status": "ok"}


class DriveCommand(BaseModel):
    left: float = Field(ge=-1, le=1, allow_inf_nan=False)
    right: float = Field(ge=-1, le=1, allow_inf_nan=False)


@app.post("/api/drive")
def drive(command: DriveCommand):
    if drive_train is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Motors unavailable",
        )
    command_timer.record_command()
    drive_train.drive(command.left, command.right)
    return {"status": "ok"}


@app.get("/api/focus")
def focus_now():
    status = build_focus_status()
    status["segments"] = tracker.segments()
    status["snack_times"] = tracker.snack_times()
    return status


class BlockCommand(BaseModel):
    action: Literal["start", "stop", "toggle"]


@app.post("/api/focus/block")
def focus_block(command: BlockCommand):
    now = time.time()
    if command.action == "toggle":
        active = tracker.toggle_block(now, source="api")
        changed = True
    else:
        active = command.action == "start"
        changed = tracker.set_block(active, now, source="api")
    return {"status": "ok", "active": active, "changed": changed}


class SignPageCommand(BaseModel):
    step: Literal[-1, 1]


@app.post("/api/sign/page")
def flip_sign_page(command: SignPageCommand):
    """The website's version of the one-hand gestures: next or previous sign page."""
    if sign_controller is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Sign is off")
    page = sign_controller.flip_page(command.step)
    return {"status": "ok", "page": page}


class AppReport(BaseModel):
    app: str = Field(min_length=1, max_length=100)


@app.post("/api/mac/app")
def mac_app(report: AppReport):
    changed = tracker.record_app(report.app.strip(), time.time())
    return {"status": "ok", "changed": changed}


class Phrase(BaseModel):
    text: str = Field(min_length=1, max_length=200)


@app.post("/api/voice/say")
def voice_say(phrase: Phrase):
    """For trying the speaker from the browser or curl. Off means it only lands in the log."""
    queued = voice.say(phrase.text)
    return {"status": "ok", "queued": queued, "backend": voice.backend}


@app.get("/api/sign.png")
def sign_png():
    """What the LED sign is showing right now, as the website preview image."""
    png = sign_preview.latest_png() if sign_controller is not None else None
    if png is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sign is off")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/stream")
async def api_stream(request: Request):
    if not _stream_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many stream connections",
        )

    return StreamingResponse(
        event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/video")
def video():
    if not _video_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many video connections",
        )

    def guarded() -> Iterator[bytes]:
        try:
            yield from frame_generator()
        finally:
            _video_slots.release()

    return StreamingResponse(
        guarded(),
        media_type=f"multipart/x-mixed-replace; boundary={FRAME_BOUNDARY}",
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
