"""uvicorn entrypoint."""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app import dedupe
from app.config import load
from app.datadog import make_route

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

cfg = load()
dedupe.init_db(cfg)

app = FastAPI(title="log-triage")
app.include_router(make_route(cfg))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=cfg.HOST, port=cfg.PORT)