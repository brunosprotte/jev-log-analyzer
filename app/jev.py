"""JEV client: POST to TypeSafe System One API, parse into TriageDecision."""
from __future__ import annotations

import httpx

from .config import Config
from .models import LogEvent, TriageDecision

QUESTIONS = [
    {
        "name": "is_bug",
        "type": "noul",
        "question": (
            "Does this log indicate a software defect requiring code change? "
            "Ignore routine info, debug, and health-check logs."
        ),
    },
    {
        "name": "severity",
        "type": "score",
        "min": 0,
        "max": 4,
        "question": (
            "Rate user/business impact: "
            "0=negligible, 1=minor, 2=moderate (some users affected), "
            "3=major (most users affected), 4=critical (outage/data loss)."
        ),
    },
    {
        "name": "category",
        "type": "choice",
        "question": "Which subsystem does this defect most likely belong to?",
        "options": ["auth", "db", "network", "ui", "perf", "infra", "config", "unknown"],
    },
    {
        "name": "is_simple_fix",
        "type": "noul",
        "question": (
            "Could an autonomous code-editing agent fix this from the log alone, "
            "without further investigation or human judgment?"
        ),
    },
    {
        "name": "requires_human",
        "type": "noul",
        "question": (
            "Does fixing this require human judgment "
            "(auth/security, schema migrations, prod data access, infra change)?"
        ),
    },
]


def _extract(payload: dict, name: str, default: float | int | str) -> float | int | str:
    answers = payload.get("answers") or {}
    a = answers.get(name) or {}
    t = a.get("type")
    if t == "noul":
        return float(a.get("noul", default))
    if t == "score":
        v = a.get("score")
        if isinstance(v, dict):
            return int(v.get("value", default))
        return int(v) if v is not None else int(default)
    if t == "choice":
        return str(a.get("choice", default))
    return default


async def triage(event: LogEvent, cfg: Config, *, client: httpx.AsyncClient | None = None) -> TriageDecision:
    state = {
        "service": event.service,
        "host": event.host,
        "level": event.level,
        "tags": event.tags,
        "timestamp": event.timestamp,
        "message": event.message,
    }
    questions = {q["name"]: {k: v for k, v in q.items() if k != "name"} for q in QUESTIONS}
    body = {"model": cfg.JEV_MODEL, "state": state, "questions": questions}

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        r = await client.post(
            cfg.JEV_BASE_URL,
            headers={
                "Authorization": f"Bearer {cfg.JEV_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        r.raise_for_status()
        payload = r.json()
    finally:
        if owns_client:
            await client.aclose()

    return TriageDecision(
        is_bug=_extract(payload, "is_bug", 0.0),  # type: ignore[arg-type]
        severity=_extract(payload, "severity", 0),  # type: ignore[arg-type]
        category=_extract(payload, "category", "unknown"),  # type: ignore[arg-type]
        is_simple_fix=_extract(payload, "is_simple_fix", 0.0),  # type: ignore[arg-type]
        requires_human=_extract(payload, "requires_human", 0.0),  # type: ignore[arg-type]
        raw=payload,
    )