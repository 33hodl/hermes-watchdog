# Hermes Watchdog

![Hermes Watchdog](docs/banner.png)

**Cron jobs that fix themselves.** A scheduled job fails at 3am and nothing tells
you. Hermes Watchdog notices, tries the fix that fits the failure, then checks
whether the next run actually worked. You only hear about it when the fix didn't
take.

Three things it does that a prompt or a skill cannot:

- **Proves the repair.** A fix counts only when Hermes's own incident and execution
  records agree it worked — the plugin cannot claim success for itself.
- **Asks the agent, not you.** When a repair would be a guess, one button hands the
  job to Hermes with the failure and its output attached, and the agent's answer
  lands in your chat.
- **Stays bounded.** Four verbs (rerun, pause, check, escalate), a daily attempt
  budget per incident, and no arbitrary shell — it cannot become a second failure
  mode.

```bash
# from the catalog — tracks the catalog pin, so `hermes update` keeps it current
hermes plugins install hermes-watchdog

# before it is merged, or to pin one exact version:
# installs like this are *held* — only `hermes plugins update hermes-watchdog` moves them
hermes plugins install 33hodl/hermes-watchdog --ref <commit-sha> --enable
# a version that adds a route needs one gateway restart — Hermes mounts
# plugin API routers when it starts
hermes gateway restart
```

**Demo (60s):** https://x.com/DiamondHandsDig/status/2119784656522588328
No API keys, no services, no Python dependencies. It reads your local cron store
and drives Hermes's own cron tool.

## Keeping it current

Catalog installs follow the catalog pin, so Hermes's own `hermes update` brings
the next version — including to anyone with `plugins.auto_apply: true`, which
applies updates unattended. A version that adds a tool, hook or capability still
asks for consent first, by design. Installs made with `--ref` are held on that
commit and only move when you run `hermes plugins update hermes-watchdog`.

## The problem it solves

Hermes already records cron failures and de-duplicates the alert. What it does not
do is *act*: a job that fails on a transient timeout keeps failing on the same
timeout, and the only remedy is a human noticing a ping and re-running it by hand.
Watchdog closes that loop with three bounded verbs — rerun, pause, escalate — and a
hard daily attempt budget per incident, so it cannot become a second failure mode.

## Using it

The page answers one question: is everything fine?

| What you see | What you do |
| --- | --- |
| **Everything is running as it should.** | Nothing. Repairs already ran and were verified against Hermes's own run record. |
| **One thing needs you.** | Read one sentence about it. If you want it fixed, press **Ask Hermes to fix it** — Watchdog hands the job to the agent with the failure, the run's output and an instruction to diagnose rather than re-run. Its answer arrives in your chat. |
| **Done** | Hides that issue and keeps it quiet — until the same error comes back, which re-opens it automatically. |
| A row of dots | That job's last five runs. Green finished, red failed, amber cancelled. One red dot and four greens is a blip; five reds is a real fault. |

Details are folded away: "What Watchdog does", "What it did recently", and per
issue "What happened, and what to do" — the numbered steps with the literal
commands, for people who would rather do it themselves.

The same things are reachable without the UI: `watchdog_status`, `watchdog_repair`
(with `dry_run`), `/watchdog` in any Hermes chat, and `hermes cron incidents ack
<id>` from a shell.

## Proof

Live, on one profile with 81 scheduled jobs: an interrupted run came back as
`health=degraded jobs=81 incidents=1`, a dry-run cycle matched it to
`builtin-escalate-unknown` and planned exactly one step, and in a throwaway
profile a timeout incident went `detected → resolved` after
`builtin-rerun-timeout` reran the job and core's own execution record confirmed
the next run succeeded. A broken scheduler script was paused and escalated
instead of retried.

### Reproduce it in one command

`scripts/proof.py` builds a throwaway `HERMES_HOME`, creates a job that fails on
its first run, and lets the repair cycle handle it. Nothing touches your real
profile, and no network is used.

```
$ python scripts/proof.py
run 1  last_status: error
incidents before: [('…f601', 'timeout', 'detected'), ('…8643', 'script', 'detected')]
cycle  health: degraded attempts: 2
  builtin-rerun-timeout -> repaired (core marked it resolved at 06:00 — Hermes's own run record)
    rerun_job ok=True reran the job: succeeded
  builtin-escalate-script -> escalated (handed to the operator (core incident marked alerted))
    pause_job ok=True paused
    escalate ok=True escalated to operator
incidents after: [('…f601', 'resolved'), ('…8643', 'alerted')]

PROOF PASSED
```

One bad run produces two incidents in core — the timeout and the non-zero exit —
and Watchdog answers them differently: a bounded rerun it can prove worked, and a
pause it escalates instead of retrying something that cannot fix itself. Neither is
left `detected`.

`python -m unittest discover -s tests` runs the engine tests and the dashboard
route tests (stdlib + FastAPI, no network). CI runs the same suite on every push.

## Example playbooks

`examples/playbooks/` ships three you can copy into
`plugin-data/hermes-watchdog/playbooks/`:

- `site-down-restart.json` — a local service died: check it is back, then rerun.
- `disk-full-pause.json` — retrying cannot free a disk: pause the job and escalate.
- `rate-limit-backoff.json` — quota errors clear: one bounded rerun.

## Why a plugin and not a skill

A skill would tell the agent how to check cron state; it would still need a human
to notice the failure first. The plugin changes what Hermes does: it reads the
cron store at runtime, fires jobs through the cron tool, runs playbooks on a hook,
and renders a Desktop pane over the same report the tools return.

## Development

```bash
python -m unittest discover -s tests -v      # 55 tests, stdlib + FastAPI
hermes plugins validate /path/to/hermes-watchdog --install-deps
hermes plugins doctor /path/to/hermes-watchdog
```

MIT licensed.
