---
name: watchdog
description: "Operate cron self-healing: read the fleet, author playbooks, verify repairs."
version: 1.0.0
author: 33hodl
license: MIT
metadata:
  hermes:
    tags: [cron, reliability, incidents, playbooks, ops]
---

# Watchdog

Use when a scheduled job (cron) has failed, is failing repeatedly, or when the user
asks why an automation stopped. The plugin turns a failure ping into a bounded,
verified repair.

## Read the fleet first

```
watchdog_status            # all jobs + open incidents + repair ledger
watchdog_status job_id=X   # one job
```

`upstream.ok: false` means Hermes's cron store could not be read — report that,
never invent an empty fleet.

## Repair

```
watchdog_repair dry_run=true   # never skip this on a fleet you have not seen
watchdog_repair                # one bounded cycle: match → act → verify → record
```

A repair counts only when Hermes's own record agrees: the incident left
`detected`/`alerted`, or a later execution of that job succeeded. "Steps ran" is
not a repair.

## Author a playbook

Built-ins exist for the failure types core classifies (rerun once on
timeout/delivery/agent, pause+escalate on script, escalate on auth/config/unknown).
A user playbook wins at equal specificity:

```
watchdog_runbooks action=save playbook={
  "id": "site-down-restart",
  "match": {"error_contains": "connection refused"},
  "steps": [
    {"verb": "check", "argv": ["systemctl", "is-active", "--quiet", "nginx"], "timeout": 10},
    {"verb": "rerun_job"}
  ],
  "max_attempts_per_day": 3
}
```

Rules that keep this safe:

- `check` steps take an argv list (no shell) — never a shell string.
- `max_attempts_per_day` is a hard budget; a loop is a second failure, not a fix.
- Never write a playbook whose steps cannot be undone.
- If the fix needs a human (credentials, a decision, a design change), the step is
  `escalate` — say so instead of retrying.

## Desktop

The **Watchdog** pane (right zone) and the status-bar chip read the same engine.
Per-incident `Repair`, `Run repair cycle` and `Plan only` all go through
`/api/plugins/hermes-watchdog/*`. The pane is opt-in: Settings → Plugins.
