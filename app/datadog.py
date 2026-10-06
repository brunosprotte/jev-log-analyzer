"""Datadog webhook ingest: parse payload, normalize to LogEvent."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from .config import Config
from .models import LogEvent
from .pipeline import handle_event

router = APIRouter()


def parse_tags(s: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not s:
        return out
    for part in s.split(","):
        if ":" in part:
            k, _, v = part.partition(":")
            out[k.strip()] = v.strip()
    return out


def parse_logs_sample(s: str | None) -> list[dict[str, Any]]:
    if not s:
        return []
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return []
    cols = data.get("columns") or []
    rows = data.get("rows") or []
    return [dict(zip(cols, row)) for row in rows]


def normalize(payload: dict[str, Any]) -> LogEvent:
    tags = parse_tags(payload.get("tags"))
    sample_rows = parse_logs_sample(payload.get("logs_sample"))
    msg = (payload.get("event_message") or "").strip()
    if not msg and sample_rows:
        first = sample_rows[0]
        msg = str(first.get("message") or first.get("msg") or json.dumps(first))
    ts_raw = payload.get("date") or payload.get("last_updated")
    if ts_raw:
        try:
            ts = datetime.fromtimestamp(int(ts_raw) / 1000, tz=timezone.utc).isoformat()
        except (ValueError, TypeError):
            ts = datetime.now(timezone.utc).isoformat()
    else:
        ts = datetime.now(timezone.utc).isoformat()
    return LogEvent(
        service=tags.get("svc") or tags.get("service") or "unknown",
        host=payload.get("host") or "unknown",
        message=msg,
        level=(payload.get("alert_type") or "info").lower(),
        tags=tags,
        timestamp=ts,
        raw=payload,
    )


def verify_hmac(body: bytes, signature: str | None, secret: str) -> bool:
    if not secret:
        return True
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.split("=", 1)[-1])


def make_route(cfg: Config) -> APIRouter:
    local_router = APIRouter()

    @local_router.post("/webhook/datadog")
    async def webhook(request: Request, bg: BackgroundTasks) -> dict[str, str]:
        body = await request.body()
        sig = request.headers.get("X-Datadog-Signature")
        if not verify_hmac(body, sig, cfg.DATADOG_WEBHOOK_SECRET):
            raise HTTPException(status_code=401, detail="bad signature")
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid json")
        event = normalize(payload)
        bg.add_task(handle_event, event, cfg)
        # Quick sig so the client has a stable id without waiting for triage.
        from .dedupe import sig_of
        return {"status": "queued", "event_id": sig_of(event)}

    return local_router