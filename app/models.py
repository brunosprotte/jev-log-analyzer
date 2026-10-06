"""Core dataclasses shared across modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class LogEvent:
    service: str
    host: str
    message: str
    level: str
    tags: dict[str, str]
    timestamp: str
    raw: dict = field(compare=False, hash=False)


@dataclass
class TriageDecision:
    is_bug: float = 0.0
    severity: int = 0
    category: str = "unknown"
    is_simple_fix: float = 0.0
    requires_human: float = 0.0
    raw: dict = field(default_factory=dict)


ActionKind = Literal["create_jira", "dispatch_agent", "store_only"]


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    decision: TriageDecision