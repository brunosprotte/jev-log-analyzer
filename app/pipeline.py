"""Orchestrates: triage -> dedupe -> execute actions."""
from __future__ import annotations

import asyncio
import logging

from . import agent, dedupe, jev, jira
from .config import Config
from .models import Action, LogEvent

log = logging.getLogger("triage")


async def _run_action(action: Action, event: LogEvent, cfg: Config, jira_key: str | None) -> tuple[str, str | None]:
    """Returns (kind, artifact_id_or_None). artifact_id: jira_key or agent_run_id."""
    if action.kind == "create_jira":
        key = await jira.create_issue(event, action.decision, cfg)
        return ("create_jira", key)
    if action.kind == "dispatch_agent":
        run_id = agent.dispatch(event, action.decision, cfg)
        return ("dispatch_agent", run_id)
    return ("store_only", None)


async def handle_event(event: LogEvent, cfg: Config) -> None:
    from .router import route

    sig = dedupe.sig_of(event)
    row = dedupe.lookup(cfg, event.service, sig)
    if row:
        dedupe.bump(cfg, row)
        if row["jira_key"]:
            try:
                # No JEV call on repeats: rebuild a minimal decision for context.
                from .models import TriageDecision
                decision = TriageDecision(category=event.tags.get("category", "unknown"))
                await jira.comment_on_issue(row["jira_key"], event, decision, row["count"], cfg)
            except Exception as e:
                log.warning("comment_on_issue failed: %s", e)
        return

    try:
        decision = await jev.triage(event, cfg)
    except Exception as e:
        log.exception("JEV triage failed: %s", e)
        return

    actions = route(decision, cfg)

    # Jira first (sync dependency: jira_key may be referenced), then the rest in parallel.
    jira_key: str | None = None
    remaining = list(actions)
    if remaining and remaining[0].kind == "create_jira":
        first = remaining.pop(0)
        try:
            _, key = await _run_action(first, event, cfg, jira_key)
            jira_key = key
        except Exception as e:
            log.warning("create_jira failed: %s", e)
        await dedupe.record(cfg, event, sig, jira_key=jira_key)

    async def _safe(a: Action) -> None:
        try:
            await _run_action(a, event, cfg, jira_key)
        except Exception as e:
            log.warning("action %s failed: %s", a.kind, e)

    if remaining:
        await asyncio.gather(*(_safe(a) for a in remaining))

    if not jira_key and remaining == []:
        # store_only path or first action failed: still record so dedupe continues.
        await dedupe.record(cfg, event, sig)