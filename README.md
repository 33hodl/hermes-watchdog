# Hermes Watchdog

**Cron jobs that fix themselves.** Watchdog reads the failures Hermes already
records, matches each one to a playbook, runs the repair, verifies it against
Hermes's own execution record, and shows the result in the Desktop app — instead
of pinging you about the same break every day until you turn the job off.

```
hermes plugins install hermes-watchdog
```

No API keys, no services, no Python dependencies. It reads your local cron store
and drives Hermes's own cron tool.

## The problem it solves

Hermes already records cron failures and de-duplicates the alert. What it does not
do is *act*: a job that fails on a transient timeout keeps failing on the same
timeout, and the only remedy is a human noticing a ping and re-running it by hand.
Watchdog closes that loop with three bounded verbs — rerun, pause, escalate — and a
hard daily attempt budget per incident, so it cannot become a second failure mode.

## What it adds

| Surface | What it does |
|---|---|
| `watchdog_status` tool | Fleet health: jobs, open incidents, failure types, 7-day repair ledger |
| `watchdog_repair` tool | One bounded cycle: match → act → **verify** → record (with `dry_run`) |
| `watchdog_runbooks` tool | List the playbooks in force, or save a new one |
| `on_session_end` hook | When a *cron* turn fails, repair that job in place before the next tick |
| `/watchdog` command | `/watchdog` for the fleet, `/watchdog repair` to run the cycle |
| Desktop pane + chip | Watchdog pane (right zone) and a status-bar health chip, per-incident Repair buttons |
| Bundled skill | `hermes-watchdog:watchdog` — how to read the fleet and author playbooks |

## Verification is the point

A repair only counts as `repaired` when Hermes's own record agrees:

1. the incident left `detected`/`alerted` (core resolves it when the job recovers), or
2. the job's latest execution finished successfully after the attempt started.

Steps that ran but did not clear the failure are recorded as `failed` — never as
success. Every attempt lands in the plugin's ledger
(`plugin-data/hermes-watchdog/data.db`) with its playbook, steps and outcome.

## Playbooks

Built-ins cover the failure types Hermes classifies (`rate_limit`, `timeout`,
`auth`, `delivery`, `config`, `script`, `agent`):

- **timeout / delivery / agent** → rerun once (2–3 attempts/day)
- **script** → pause the job, then escalate
- **auth / config / unknown** → escalate; never guess at a repair

Your own playbooks live in `plugin-data/hermes-watchdog/playbooks/*.json` and win
over built-ins at equal specificity:

```json
{
  "id": "site-down-restart",
  "match": { "error_contains": "connection refused" },
  "steps": [
    { "verb": "check", "argv": ["systemctl", "is-active", "--quiet", "nginx"], "timeout": 10 },
    { "verb": "rerun_job" }
  ],
  "max_attempts_per_day": 3
}
```

Verbs: `rerun_job`, `pause_job`, `check` (argv list, no shell), `escalate`.

## Disclosure

- **Reads:** your profile's cron store (`cron/jobs.py`, `cron/incidents.py`,
  `cron/executions.py`) read-only, through late imports so an upstream rename
  degrades to "upstream unavailable" instead of a crash.
- **Runs:** `rerun_job` fires the job through Hermes's own `cronjob` tool (the same
  path `hermes cron run` uses); `pause_job` pauses it; `check` runs the argv list a
  **user-authored playbook** declares, with no shell and a per-step timeout.
- **Writes:** only its own plugin data directory (`plugin-data/hermes-watchdog/`).
- **Never:** posts, messages, or edits your jobs' prompts/schedules. `pause_job` is
  the only mutation of job state and it is only reachable from a playbook you wrote.
- **Upstream note (catalog rule 9):** Hermes has no public seam for reading cron
  incidents, so the plugin imports three documented-in-code modules and the
  `cronjob` tool. Every reader is wrapped; a missing module shows as
  `upstream.ok: false` in the pane and tools. A read-only cron-health hook would
  remove those imports — tracked as an upstream issue.

## Desktop pane

The pane is opt-in (Settings → Plugins), like every unified-package Desktop half.
It polls `/api/plugins/hermes-watchdog/status` every 15s and posts
`/repair`, so the pane, the tools and the hook can never disagree.

## Development

```bash
python -m unittest discover -s tests -v      # 14 tests, stdlib unittest
hermes plugins validate /path/to/hermes-watchdog --install-deps
hermes plugins doctor /path/to/hermes-watchdog
```

MIT licensed.
