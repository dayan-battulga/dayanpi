from contextlib import asynccontextmanager
from fastapi import FastAPI

import collector

sampler = collector.RateSampler("wlan0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sampler.sample()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/api/status")
def stats():
    return collector.snapshot(sampler)
