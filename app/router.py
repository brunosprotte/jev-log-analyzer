"""Pure decision: TriageDecision -> [Action]. No I/O."""
from __future__ import annotations

from .config import Config
from .models import Action, TriageDecision


def route(decision: TriageDecision, cfg: Config) -> list[Action]:
    actions: list[Action] = []
    if decision.is_bug >= cfg.IS_BUG_MIN:
        actions.append(Action("create_jira", decision))
    if (
        decision.is_simple_fix >= cfg.IS_SIMPLE_FIX_MIN
        and decision.requires_human <= cfg.REQUIRES_HUMAN_MAX
        and decision.severity <= cfg.SEVERITY_MAX_FOR_AGENT
    ):
        actions.append(Action("dispatch_agent", decision))
    if not actions:
        actions.append(Action("store_only", decision))
    return actions