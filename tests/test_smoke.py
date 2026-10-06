"""Smoke test: pure logic only, no network. Run: python tests/test_smoke.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Allow running as a script without `pip install -e .`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config
from app.dedupe import init_db, normalize, sig_of
from app.models import LogEvent, TriageDecision
from app.router import route


def _cfg(tmp_db: str) -> Config:
    return Config(
        HOST="0.0.0.0", PORT=8080, DATADOG_WEBHOOK_SECRET="",
        JEV_API_KEY="", JEV_MODEL="jev-latest", JEV_BASE_URL="",
        JIRA_SITE="", JIRA_EMAIL="", JIRA_API_TOKEN="",
        JIRA_PROJECT_KEY="OPS", JIRA_ISSUE_TYPE="Bug",
        CLAUDE_BIN="claude", AGENT_REPO_ROOT="C:/repos/svc",
        AGENT_BUDGET_USD=3.0, AGENT_TIMEOUT_S=600,
        DEDUPE_DB_PATH=tmp_db, DEDUPE_WINDOW_HOURS=24,
        IS_BUG_MIN=0.7, IS_SIMPLE_FIX_MIN=0.6,
        REQUIRES_HUMAN_MAX=0.3, SEVERITY_MAX_FOR_AGENT=2,
    )


def _event(msg: str = "db timeout in checkout", service: str = "checkout", level: str = "error") -> LogEvent:
    return LogEvent(
        service=service, host="api-1", message=msg, level=level,
        tags={"svc": service, "env": "prod"}, timestamp="2026-10-05T14:23:00Z",
        raw={"alert_type": level, "event_message": msg, "tags": f"svc:{service},env:prod"},
    )


def test_router():
    cfg = _cfg(":memory:")
    cases = [
        (_event(), TriageDecision(is_bug=0.95, severity=3, category="db",
                                  is_simple_fix=0.2, requires_human=0.1),
         ["create_jira"]),
        (_event("retry succeeded"), TriageDecision(is_bug=0.4, severity=2, category="network",
                                                   is_simple_fix=0.1, requires_human=0.2),
         ["store_only"]),
        (_event("healthcheck ok"), TriageDecision(is_bug=0.05, severity=0, category="unknown",
                                                  is_simple_fix=0.0, requires_human=0.0),
         ["store_only"]),
        (_event("null pointer in parser"), TriageDecision(is_bug=0.92, severity=1, category="auth",
                                                         is_simple_fix=0.85, requires_human=0.05),
         ["create_jira", "dispatch_agent"]),
    ]
    for ev, dec, expected in cases:
        got = [a.kind for a in route(dec, cfg)]
        assert got == expected, f"event={ev.message!r} got={got} expected={expected}"


def test_normalize():
    n = normalize("db timeout at 2026-10-05T14:23:00Z from 10.0.0.5:5432 req=42 trace=abc123")
    assert "<TS>" in n and "<IP>" in n and ":<PORT>" in n and "<N>" in n


def test_sig_stable_and_strippable():
    a = _event("db timeout at 2026-10-05T14:23:00Z from 10.0.0.5")
    b = _event("db timeout at 2026-10-06T09:01:11Z from 10.0.0.7")
    c = _event("different message")
    assert sig_of(a) == sig_of(b)  # same normalized shape -> same sig
    assert sig_of(a) != sig_of(c)


def test_dedupe_roundtrip():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        path = tmp.name
    cfg = _cfg(path)
    init_db(cfg)
    ev = _event()
    sig = sig_of(ev)
    from app.dedupe import lookup, record, bump
    assert lookup(cfg, ev.service, sig) is None
    row = record(cfg, ev, sig, jira_key="OPS-1")
    assert row["count"] == 1
    bump(cfg, row)
    again = lookup(cfg, ev.service, sig)
    assert again is not None and again["count"] == 2 and again["jira_key"] == "OPS-1"


def main() -> None:
    test_router()
    test_normalize()
    test_sig_stable_and_strippable()
    test_dedupe_roundtrip()
    print("OK")


if __name__ == "__main__":
    main()