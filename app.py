import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import collector
from camera import CameraStream

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

FRAME_BOUNDARY = "frame"
FRAME_TIMEOUT_S = 5.0
MAX_CONSECUTIVE_TIMEOUTS = 3
SNAPSHOT_INTERVAL_S = 1.0

logger = logging.getLogger(__name__)

sampler = collector.RateSampler("wlan0")
stream = CameraStream("/dev/video0")
latest_snapshot: dict | None = None


async def snapshot_producer() -> None:
    """One owner of the sampler; SSE clients only read latest_snapshot."""
    global latest_snapshot
    while True:
        try:
            latest_snapshot = collector.snapshot(sampler)
        except Exception:
            logger.exception("snapshot producer failed")
        await asyncio.sleep(SNAPSHOT_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sampler.sample()
    stream.start()
    producer = asyncio.create_task(snapshot_producer(), name="snapshot-producer")
    yield
    producer.cancel()
    try:
        await producer
    except asyncio.CancelledError:
        pass
    stream.stop()


app = FastAPI(lifespan=lifespan)


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
        logger.info("SSE client disconnected")


@app.get("/api/stats")
def stats():
    return latest_snapshot if latest_snapshot is not None else {}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/stream")
async def api_stream(request: Request):
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
    return StreamingResponse(
        frame_generator(),
        media_type=f"multipart/x-mixed-replace; boundary={FRAME_BOUNDARY}",
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
