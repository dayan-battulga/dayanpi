from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import collector

sampler = collector.RateSampler("wlan0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sampler.sample()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/api/stats")
def stats():
    return collector.snapshot(sampler)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
