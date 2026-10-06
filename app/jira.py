"""Jira Cloud REST v3: build ADF, create issue, comment on issue."""
from __future__ import annotations

import base64
import json

import httpx

from .config import Config
from .models import LogEvent, TriageDecision


def _para(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def _heading(text: str) -> dict:
    return {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": text}]}


def _code(text: str, lang: str = "json") -> dict:
    return {
        "type": "codeBlock",
        "attrs": {"language": lang},
        "content": [{"type": "text", "text": text}],
    }


def _bullet(items: list[str]) -> dict:
    return {
        "type": "bulletList",
        "content": [{"type": "listItem", "content": [_para(t)]} for t in items],
    }


def build_adf(event: LogEvent, decision: TriageDecision) -> dict:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            _heading("Datadog Event"),
            _code(event.message, "text"),
            _heading("Host / Service / Level"),
            _bullet([f"service: {event.service}", f"host: {event.host}", f"level: {event.level}"]),
            _heading("JEV Triage"),
            _bullet([
                f"is_bug: {decision.is_bug:.2f}",
                f"severity: {decision.severity}",
                f"category: {decision.category}",
                f"is_simple_fix: {decision.is_simple_fix:.2f}",
                f"requires_human: {decision.requires_human:.2f}",
            ]),
            _heading("Tags"),
            _bullet([f"{k}: {v}" for k, v in event.tags.items()] or ["(none)"]),
            _heading("Raw payload"),
            _code(json.dumps(event.raw, indent=2, ensure_ascii=False)),
        ],
    }


def _auth(cfg: Config) -> str:
    pair = f"{cfg.JIRA_EMAIL}:{cfg.JIRA_API_TOKEN}".encode("utf-8")
    return "Basic " + base64.b64encode(pair).decode("ascii")


def _summary(event: LogEvent, decision: TriageDecision, *, repeat: int = 1) -> str:
    msg = event.message.replace("\n", " ").strip()[:80]
    suffix = f" (x{repeat})" if repeat > 1 else ""
    return f"[{event.service}] {decision.category} - {msg}{suffix}"


def _labels(event: LogEvent, decision: TriageDecision) -> list[str]:
    out = {"datadog", "auto-triage", f"service:{event.service}", f"category:{decision.category}"}
    if event.level:
        out.add(f"level:{event.level}")
    return sorted(out)


async def create_issue(event: LogEvent, decision: TriageDecision, cfg: Config,
                       *, repeat: int = 1,
                       client: httpx.AsyncClient | None = None) -> str:
    url = f"https://{cfg.JIRA_SITE}/rest/api/3/issue"
    body = {
        "fields": {
            "project": {"key": cfg.JIRA_PROJECT_KEY},
            "summary": _summary(event, decision, repeat=repeat),
            "issuetype": {"name": cfg.JIRA_ISSUE_TYPE},
            "description": build_adf(event, decision),
            "labels": _labels(event, decision),
        }
    }
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        r = await client.post(url, headers={
            "Authorization": _auth(cfg),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }, json=body)
        r.raise_for_status()
        return r.json()["key"]
    finally:
        if owns:
            await client.aclose()


async def comment_on_issue(key: str, event: LogEvent, decision: TriageDecision,
                           count: int, cfg: Config,
                           *, client: httpx.AsyncClient | None = None) -> None:
    url = f"https://{cfg.JIRA_SITE}/rest/api/3/issue/{key}/comment"
    doc = build_adf(event, decision)
    doc["content"].insert(0, _para(f"occurrence #{count}"))
    body = {"body": doc}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        r = await client.post(url, headers={
            "Authorization": _auth(cfg),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }, json=body)
        r.raise_for_status()
    finally:
        if owns:
            await client.aclose()