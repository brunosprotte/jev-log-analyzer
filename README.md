# jev-log-analyzer

Datadog webhook → JEV triage → Jira ticket + Claude Code auto-fix.

A small FastAPI service that receives Datadog log alerts, classifies each one with the [TypeSafe System One / JEV](https://docs.typesafe.ai/api) model, and decides what to do: ignore, file a Jira bug, and/or spawn a headless [Claude Code CLI](https://docs.claude.com/en/docs/claude-code) agent to fix the bug and open a PR.

## Architecture

```
        ┌────────────┐    POST     ┌──────────────┐
        │  Datadog   │────────────▶│  /webhook/   │
        │  Monitor   │  webhook    │  datadog     │
        └────────────┘             └──────┬───────┘
                                          │ LogEvent
                                          ▼
                              ┌─────────────────────┐
                              │  dedupe (SQLite,    │
                              │  sha1(normalized))  │
                              └──────┬──────────────┘
                                     │ new sig
                                     ▼
                              ┌─────────────────────┐
                              │  JEV triage         │
                              │  is_bug, severity,  │
                              │  category, simple,  │
                              │  requires_human     │
                              └──────┬──────────────┘
                                     │ TriageDecision
                                     ▼
                              ┌─────────────────────┐
                              │  router (pure)      │
                              └──────┬──────────────┘
                                     │ Action[]
                                     │
              ┌──────────────────────┼─────────────────────────┐
              ▼                      ▼                         ▼
       ┌─────────────┐      ┌────────────────┐        ┌──────────────┐
       │ create_jira │      │ dispatch_agent │        │  store_only  │
       │ POST /issue │      │ claude -p …    │        │  (no-op)     │
       └─────────────┘      │ → git commit   │        └──────────────┘
                            │ → gh pr create │
                            └────────────────┘
```

## Requirements

- Python ≥ 3.12
- Windows / macOS / Linux (developed on Windows 11 + Python 3.14)
- For the AI agent: [Claude Code CLI](https://docs.claude.com/en/docs/claude-code) on `PATH` and a Git repo with `gh` authenticated
- For production Datadog: a public URL (e.g. `cloudflared tunnel --url http://localhost:8080`)

## Install

```powershell
git clone https://github.com/brunosprotte/jev-log-analyzer
cd jev-log-analyzer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
# edit .env (see Configuration)
python tests\test_smoke.py     # should print "OK"
```

## Configuration

All settings live in `.env` (loaded once at startup).

| Var | Purpose | Required |
|---|---|---|
| `JEV_API_KEY` | TypeSafe API key (Bearer token for `api.typesafe.ai/v1/systemone`) | yes (for triage) |
| `JEV_MODEL` | Model id, default `jev-latest` | no |
| `JEV_BASE_URL` | API endpoint, default `https://api.typesafe.ai/v1/systemone` | no |
| `JIRA_SITE` | `<tenant>.atlassian.net` | yes (for Jira) |
| `JIRA_EMAIL` | Atlassian account email | yes (for Jira) |
| `JIRA_API_TOKEN` | Atlassian API token (https://id.atlassian.com/manage-profile/security/api-tokens) | yes (for Jira) |
| `JIRA_PROJECT_KEY` | e.g. `OPS` | yes |
| `JIRA_ISSUE_TYPE` | e.g. `Bug` | no |
| `CLAUDE_BIN` | Path to `claude` CLI | yes (for agent) |
| `AGENT_REPO_ROOT` | Absolute path to repo the agent edits (e.g. `C:/repos/checkout-service`) | yes (for agent) |
| `AGENT_BUDGET_USD` | Max spend per agent run | no, default `3.00` |
| `AGENT_TIMEOUT_S` | Max seconds per agent run | no, default `600` |
| `DATADOG_WEBHOOK_SECRET` | HMAC sha256 secret; blank = skip verification | no |
| `DEDUPE_DB_PATH` | SQLite file | no, default `./dedupe.sqlite` |
| `DEDUPE_WINDOW_HOURS` | Dedupe window | no, default `24` |
| `IS_BUG_MIN` | Threshold for filing a ticket | no, default `0.7` |
| `IS_SIMPLE_FIX_MIN` | Threshold for spawning an agent | no, default `0.6` |
| `REQUIRES_HUMAN_MAX` | Below this means low-risk to auto-fix | no, default `0.3` |
| `SEVERITY_MAX_FOR_AGENT` | Only fix low-severity bugs autonomously | no, default `2` |
| `HOST`, `PORT` | uvicorn bind | no, defaults `0.0.0.0:8080` |

## Usage

### 1. Smoke test (no network)

```powershell
python tests\test_smoke.py
```

Asserts router decisions for 4 fixture scenarios, message normalization, sig stability, and a dedupe round-trip.

### 2. Local server + curl (no Datadog/JEV/Jira credentials)

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

```bash
curl http://127.0.0.1:8080/health
# {"status":"ok"}

curl -X POST http://127.0.0.1:8080/webhook/datadog \
  -H "Content-Type: application/json" \
  -d '{"alert_type":"error","event_message":"db timeout in checkout","host":"api-1",
       "tags":"svc:checkout,env:prod","date":"1700000000000","alert_id":"1",
       "alert_title":"err","alert_status":"err","alert_transition":"Triggered",
       "event_type":"log_alert","event_url":"x","priority":"normal","users":""}'
# {"status":"queued","event_id":"19d71f218ad1aa1a"}
```

Without `JEV_API_KEY` the pipeline logs an exception and the webhook still returns 200 — by design, so a Datadog retry storm never cascades.

### 3. End-to-end (real credentials)

After populating `.env`:

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8080
cloudflared tunnel --url http://localhost:8080   # paste the https URL into Datadog
```

Then trigger a real alert (or re-curl the same payload above). Expected results:
- `INFO` line in logs (no exception)
- A Jira issue appears with the ADF description and labels
- If `is_simple_fix > 0.6` and `severity ≤ 2`: a real PR is opened in `AGENT_REPO_ROOT`
- Re-sending the same payload: existing Jira issue receives a comment, no new ticket, no new agent dispatch

## JEV question set

Sent in a single `POST /v1/systemone` per log:

| name | type | purpose |
|---|---|---|
| `is_bug` | noul | Is this a defect requiring code change? |
| `severity` | score 0-4 | User/business impact (0=negligible, 4=critical) |
| `category` | choice | `auth` / `db` / `network` / `ui` / `perf` / `infra` / `config` / `unknown` |
| `is_simple_fix` | noul | Can a code-editing agent fix it from the log alone? |
| `requires_human` | noul | Needs human judgment (auth/security, schema, prod data)? |

See `app/jev.py` for the exact phrasing.

## Dedupe

`normalize()` strips timestamps, hex hashes, UUIDs, IPv4, ports, and numeric ids from the message. The dedupe key is `sha1(f"{service}|{normalized}")[:16]`. Within `DEDUPE_WINDOW_HOURS` the same signature increments a counter, comments on the existing Jira ticket, and skips the agent. Different signatures trigger a fresh triage + ticket + agent run.

## Datadog setup

1. **Integrations → Webhooks → New.** URL = `https://<your-public-host>/webhook/datadog`. Custom payload should include: `$ALERT_ID`, `$ALERT_TITLE`, `$ALERT_STATUS`, `$ALERT_TRANSITION`, `$ALERT_TYPE`, `$EVENT_MESSAGE`, `$EVENT_TITLE`, `$EVENT_TYPE`, `$EVENT_URL`, `$HOSTNAME`, `$PRIORITY`, `$TAGS`, `$LOGS_SAMPLE`.
2. **Monitors → New → Logs.** Query e.g. `service:auth status:error`. In the notify section, add `@<your-webhook-name>`.

Only logs that match the monitor query hit this service — keeps JEV costs predictable.

## Troubleshooting

- **Webhook returns 200 but nothing else happens**: check uvicorn logs for `JEV triage failed` or `create_jira failed`. Most often a missing env var.
- **`Illegal header value b'Bearer '`**: `JEV_API_KEY` is empty.
- **429 / 529 from JEV**: rate-limited or overloaded. The service logs and drops; not retried (add tenacity when needed).
- **`gh pr create` fails in agent**: `gh` is not authenticated, or `AGENT_REPO_ROOT` is not a git repo.

## Costs

- Datadog: paid plan, logs billed per GB ingested. Use narrow monitor queries to limit volume.
- JEV (TypeSafe): per-call token usage returned in `usage` field; one call per new log signature.
- Jira: Atlassian Cloud subscription.
- Claude Code: spend capped per agent run by `AGENT_BUDGET_USD`.

## Limitations / upgrade path

- **Single JEV call per log**: 5 questions batched. Could split cheap noul questions from expensive score/choice to optimize cost.
- **No retry/backoff**: 429/529 only logged. Add `tenacity` when needed.
- **One repo for the agent**: `AGENT_REPO_ROOT` is a single path. Add `repo_by_service` map when ≥ 2 services.
- **HMAC optional**: Datadog signature verification is skipped when `DATADOG_WEBHOOK_SECRET` is blank.
- **No archival**: only dedupe rows in SQLite. Add `events_archive` table when audit is needed.
- **No streaming per-log**: only Datadog Monitor → webhook. Switch to Log Forwarding HTTP destination for every-log ingestion.

## License

MIT.