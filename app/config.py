"""Single Config dataclass loaded from env at startup."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    return float(raw) if raw not in (None, "") else default


def _int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Config:
    HOST: str
    PORT: int
    DATADOG_WEBHOOK_SECRET: str

    JEV_API_KEY: str
    JEV_MODEL: str
    JEV_BASE_URL: str

    JIRA_SITE: str
    JIRA_EMAIL: str
    JIRA_API_TOKEN: str
    JIRA_PROJECT_KEY: str
    JIRA_ISSUE_TYPE: str

    CLAUDE_BIN: str
    AGENT_REPO_ROOT: str
    AGENT_BUDGET_USD: float
    AGENT_TIMEOUT_S: int

    DEDUPE_DB_PATH: str
    DEDUPE_WINDOW_HOURS: int

    IS_BUG_MIN: float
    IS_SIMPLE_FIX_MIN: float
    REQUIRES_HUMAN_MAX: float
    SEVERITY_MAX_FOR_AGENT: int


def load() -> Config:
    # Best-effort dotenv; stdlib only.
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

    return Config(
        HOST=_env("HOST", "0.0.0.0"),
        PORT=_int("PORT", 8080),
        DATADOG_WEBHOOK_SECRET=_env("DATADOG_WEBHOOK_SECRET"),
        JEV_API_KEY=_env("JEV_API_KEY"),
        JEV_MODEL=_env("JEV_MODEL", "jev-latest"),
        JEV_BASE_URL=_env("JEV_BASE_URL", "https://api.typesafe.ai/v1/systemone"),
        JIRA_SITE=_env("JIRA_SITE"),
        JIRA_EMAIL=_env("JIRA_EMAIL"),
        JIRA_API_TOKEN=_env("JIRA_API_TOKEN"),
        JIRA_PROJECT_KEY=_env("JIRA_PROJECT_KEY", "OPS"),
        JIRA_ISSUE_TYPE=_env("JIRA_ISSUE_TYPE", "Bug"),
        CLAUDE_BIN=_env("CLAUDE_BIN", "claude"),
        AGENT_REPO_ROOT=_env("AGENT_REPO_ROOT", "C:/repos/svc"),
        AGENT_BUDGET_USD=_float("AGENT_BUDGET_USD", 3.0),
        AGENT_TIMEOUT_S=_int("AGENT_TIMEOUT_S", 600),
        DEDUPE_DB_PATH=_env("DEDUPE_DB_PATH", "./dedupe.sqlite"),
        DEDUPE_WINDOW_HOURS=_int("DEDUPE_WINDOW_HOURS", 24),
        IS_BUG_MIN=_float("IS_BUG_MIN", 0.7),
        IS_SIMPLE_FIX_MIN=_float("IS_SIMPLE_FIX_MIN", 0.6),
        REQUIRES_HUMAN_MAX=_float("REQUIRES_HUMAN_MAX", 0.3),
        SEVERITY_MAX_FOR_AGENT=_int("SEVERITY_MAX_FOR_AGENT", 2),
    )