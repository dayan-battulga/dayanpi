from contextlib import asynccontextmanager
from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import collector
from camera import CameraStream

FRAME_BOUNDARY = "frame"
FRAME_TIMEOUT_S = 5.0
MAX_CONSECUTIVE_TIMEOUTS = 3

sampler = collector.RateSampler("wlan0")
stream = CameraStream("/dev/video0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sampler.sample()
    stream.start()
    yield
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


@app.get("/api/stats")
def stats():
    return collector.snapshot(sampler)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/video")
def video():
    return StreamingResponse(
        frame_generator(),
        media_type=f"multipart/x-mixed-replace; boundary={FRAME_BOUNDARY}",
    )


app.mount("/", StaticFiles(directory="static", html=True), name="static")
