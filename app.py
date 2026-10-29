import asyncio
import base64
import json
import logging
import os
import secrets
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from typing import Literal

import collector
import focus_worker
from camera import CameraStream
from drivetrain import CommandTimer, DriveTrain
from focus import FocusLog, FocusTracker, FocusUpdate, day_key
from focus_worker import FocusWorker
from voice import VoiceAnnouncer

# uvicorn only configures its own loggers; without this the app's INFO lines
# ("focus tracker running", "voice off, would say ...") never reach journalctl.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("DAYANPI_DATA_DIR", str(BASE_DIR / "data")))
FOCUS_LOG_DIR = DATA_DIR / "focus_log"

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
stream = CameraStream("/dev/video0")
latest_snapshot: dict | None = None
drive_train: DriveTrain | None = None
command_timer = CommandTimer(DRIVE_TIMEOUT_S)
focus_log = FocusLog(FOCUS_LOG_DIR)
tracker = FocusTracker(focus_log, started_at=time.time())
worker: FocusWorker | None = None
voice = VoiceAnnouncer()

_video_active = 0
_stream_active = 0
_video_lock = threading.Lock()
_stream_lock = threading.Lock()

limiter = Limiter(key_func=get_remote_address)


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


def focus_status() -> dict:
    status = tracker.status(time.time())
    status["enabled"] = worker is not None
    status["voice"] = {"enabled": voice.enabled, "backend": voice.backend, "problem": voice.problem}
    return status


def handle_focus_update(update: FocusUpdate, now: float) -> None:
    """Runs on the worker thread after every check. Callouts fan out to the speaker and the sign from here."""
    for callout in update.callouts:
        logger.info("focus callout %s: %s", callout.name, callout.text)
        if callout.speak:
            voice.say(callout.text)


def handle_gesture(name: str, now: float) -> None:
    """Runs on the worker thread when a held gesture fires."""
    tracker.record_gesture(name, now)
    if name == "toggle_block":
        active = tracker.status(now)["block"]["active"]
        tracker.set_block(not active, now, source="gesture")
        voice.say("Block stopped." if active else "Block started.")


def start_focus_worker() -> FocusWorker | None:
    started = None
    scanner = focus_worker.build_scanner()
    if scanner is not None:
        now = time.time()
        restored = tracker.restore(focus_log.read_day(day_key(now)), now)
        if restored:
            logger.info("focus tracker restored %s events from today's log", restored)
        started = FocusWorker(stream, scanner, tracker, on_update=handle_focus_update, on_gesture=handle_gesture)
        started.start()
        logger.info("focus tracker running; log in %s", FOCUS_LOG_DIR)
    return started


async def snapshot_producer() -> None:
    """One owner of the sampler; SSE clients only read latest_snapshot."""
    global latest_snapshot
    while True:
        try:
            snapshot = collector.snapshot(sampler)
            snapshot["focus"] = focus_status()
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
    global drive_train, worker
    if not AUTH_USER or not AUTH_PASSWORD:
        raise RuntimeError(
            "DAYANPI_USER and DAYANPI_PASSWORD must be set "
            "(e.g. via EnvironmentFile=/etc/dayanpi.env)"
        )
    sampler.sample()
    stream.start()
    voice.start()
    worker = start_focus_worker()
    drive_train = None
    watchdog = None
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
            try:
                await watchdog
            except asyncio.CancelledError:
                pass
            drive_train.close()
    producer.cancel()
    try:
        await producer
    except asyncio.CancelledError:
        pass
    if worker is not None:
        worker.stop()
        worker = None
    voice.stop()
    stream.stop()


app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


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
    global _stream_active
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
        with _stream_lock:
            _stream_active = max(0, _stream_active - 1)
        logger.info("SSE client disconnected")


@app.get("/api/stats")
@limiter.limit("60/minute")
def stats(request: Request):
    return latest_snapshot if latest_snapshot is not None else {}


@app.get("/api/health")
@limiter.limit("60/minute")
def health(request: Request):
    return {"status": "ok"}


class DriveCommand(BaseModel):
    left: float = Field(ge=-1, le=1, allow_inf_nan=False)
    right: float = Field(ge=-1, le=1, allow_inf_nan=False)


@app.post("/api/drive")
@limiter.limit("600/minute")
def drive(request: Request, command: DriveCommand):
    if drive_train is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Motors unavailable",
        )
    command_timer.record_command()
    drive_train.drive(command.left, command.right)
    return {"status": "ok"}


@app.get("/api/focus")
@limiter.limit("60/minute")
def focus_now(request: Request):
    status = focus_status()
    status["segments"] = tracker.segments()
    return status


class BlockCommand(BaseModel):
    action: Literal["start", "stop", "toggle"]


@app.post("/api/focus/block")
@limiter.limit("30/minute")
def focus_block(request: Request, command: BlockCommand):
    now = time.time()
    active = tracker.status(now)["block"]["active"]
    wanted = {"start": True, "stop": False, "toggle": not active}[command.action]
    changed = tracker.set_block(wanted, now, source="api")
    return {"status": "ok", "active": wanted, "changed": changed}


class AppReport(BaseModel):
    app: str = Field(min_length=1, max_length=100)


@app.post("/api/mac/app")
@limiter.limit("120/minute")
def mac_app(request: Request, report: AppReport):
    changed = tracker.record_app(report.app.strip(), time.time())
    return {"status": "ok", "changed": changed}


class Phrase(BaseModel):
    text: str = Field(min_length=1, max_length=200)


@app.post("/api/voice/say")
@limiter.limit("30/minute")
def voice_say(request: Request, phrase: Phrase):
    """For trying the speaker from the browser or curl. Off means it only lands in the log."""
    queued = voice.say(phrase.text)
    return {"status": "ok", "queued": queued, "backend": voice.backend}


@app.get("/api/stream")
@limiter.limit("5/minute")
async def api_stream(request: Request):
    global _stream_active
    with _stream_lock:
        if _stream_active >= STREAM_MAX_CONCURRENT:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Too many stream connections",
            )
        _stream_active += 1

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
@limiter.limit("30/minute")
def video(request: Request):
    global _video_active

    with _video_lock:
        if _video_active >= VIDEO_MAX_CONCURRENT:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Too many video connections",
            )
        _video_active += 1

    def guarded() -> Iterator[bytes]:
        global _video_active
        try:
            yield from frame_generator()
        finally:
            with _video_lock:
                _video_active = max(0, _video_active - 1)

    return StreamingResponse(
        guarded(),
        media_type=f"multipart/x-mixed-replace; boundary={FRAME_BOUNDARY}",
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
