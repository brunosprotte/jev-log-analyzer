"""Spawn `claude` headless to fix a defect and open a PR."""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from .config import Config
from .models import LogEvent, TriageDecision


def _prompt(event: LogEvent, decision: TriageDecision, cfg: Config) -> str:
    return (
        f"Investigate and fix the following defect in the repo at {cfg.AGENT_REPO_ROOT}.\n"
        f"Service: {event.service}\nCategory: {decision.category}\n"
        f"Log:\n{event.message}\n\n"
        "Workflow:\n"
        "1. Read enough of the repo to locate the cause.\n"
        "2. Make the minimal fix.\n"
        "3. Run the project's tests if they exist.\n"
        "4. `git add -A`, `git commit -m 'fix: <short>'`, `gh pr create --fill`.\n"
        "5. Reference this defect in the PR body and print the PR URL."
    )


def dispatch(event: LogEvent, decision: TriageDecision, cfg: Config) -> str:
    run_id = uuid.uuid4().hex
    out_dir = Path("data/agent_runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"{run_id}.json"

    cmd = [
        cfg.CLAUDE_BIN, "-p", "--bare",
        "--dangerously-skip-permissions",
        "--add-dir", cfg.AGENT_REPO_ROOT,
        "--max-budget-usd", str(cfg.AGENT_BUDGET_USD),
        "--output-format", "json",
        _prompt(event, decision, cfg),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=cfg.AGENT_TIMEOUT_S)
        result = {
            "run_id": run_id,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired as e:
        result = {
            "run_id": run_id,
            "returncode": -1,
            "stdout": e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""),
            "stderr": f"timeout after {cfg.AGENT_TIMEOUT_S}s",
        }
    log_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return run_id