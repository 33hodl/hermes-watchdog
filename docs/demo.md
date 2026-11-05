# Demo video — 90 seconds, no cuts you can't follow

Rules from the hackathon post: **under 90 seconds**, show the plugin *working*,
tag `@NousResearch`, post on X, and submit the link with the catalog PR URL.

Record on the Mac (Hermes Desktop), 16:9 or 1:1. Talk over it — the narration below
is written to be said, not read.

## Before you hit record

```bash
hermes plugins list | grep watchdog          # enabled
hermes cron list                             # note one job id you can point at
```

Open Desktop → **⌘K → Reload desktop plugins**, then Settings → Plugins →
**Watchdog → on**. The Watchdog pane docks on the right; the chip sits in the
status bar. `/watchdog` in the chat is the fallback if the pane misbehaves on
camera.

## Shot list

| time | on screen | say |
|---|---|---|
| 0:00–0:08 | Desktop, Watchdog pane open, chip visible | "Hermes already tells you when a cron job fails. It doesn't do anything about it." |
| 0:08–0:18 | `/watchdog` typed in chat → fleet line + the open incident | "This is the dispatcher's own record: eighty-one scheduled jobs, one open incident — an interrupted run." |
| 0:18–0:30 | click **Plan only** in the pane → toast "1 incident would be repaired" | "Plan first. Watchdog matched it to a playbook and shows exactly what it would run — no guessing, no shell strings." |
| 0:30–0:45 | click **Run repair cycle** → toast, then the row in *Recent repairs* with `failed`/`escalated` | "It runs the playbook, then verifies against Hermes's own execution record. This one escalates — an interruption needs a human — and it says so instead of pretending it fixed it." |
| 0:45–1:05 | open the agent chat, ask: *"Show me the playbooks and write one that reruns my digest on a timeout"* → `watchdog_runbooks` output, saved file path | "Playbooks are data, not prompts. Built-ins for what Hermes classifies — timeout, delivery, auth, script — and you can write your own in one JSON file." |
| 1:05–1:22 | terminal: `cat ~/.hermes/plugin-data/hermes-watchdog/playbooks/*.json`, then `sqlite3 ~/.hermes/plugin-data/hermes-watchdog/data.db 'select job_name,playbook,outcome from repairs'` | "Every attempt is a row: playbook, steps, outcome, and a hard daily budget per incident so a repair loop can't become the next outage." |
| 1:22–1:30 | the pane one last time, chip green/amber | "Watchdog. Cron jobs that fix themselves. Catalog PR linked below." |

## Post copy

> Hermes Agent Plugin Hackathon entry: **Watchdog** — cron jobs that fix themselves.
>
> Hermes records cron failures and de-dupes the alert. Watchdog acts: it matches each
> open incident to a playbook, runs a bounded repair (rerun, pause, check, escalate),
> then verifies the failure actually cleared against Hermes's own incident and
> execution records. Steps that ran but didn't fix anything are recorded as failures,
> never as wins.
>
> Three tools, a `/watchdog` command, an `on_session_end` hook that repairs a failing
> cron turn in place, a bundled skill, and a Desktop pane + status chip.
>
> Catalog PR: <PR link> · github: github.com/33hodl/hermes-watchdog
>
> @NousResearch

## Submission form

Needs: (1) catalog PR link, (2) demo video URL. Files due **5PM EST Nov 11**
(06:00 SGT Nov 12). Submit as soon as the PR is open — the rules say you can.

- PR: https://github.com/NousResearch/hermes-agent/pull/149270
- Repo: https://github.com/33hodl/hermes-watchdog
- Seam request referenced in the PR: https://github.com/NousResearch/hermes-agent/issues/149262

## If something looks wrong on camera

- Pane empty / "backend unreachable" → the gateway needs a restart after install
  (`systemctl --user restart hermes-gateway`), then ⌘K → Reload desktop plugins.
- Chip says `watchdog` with no number → that is the green state, 0 open incidents.
- `/watchdog repair` in chat is the whole story without any UI.
