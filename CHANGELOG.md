# Changelog

Everything here was found by running the plugin on a real Desktop client, not by
reading the code. Each fix is one behaviour that made a click look like a no-op.

## 0.5.1

- **The status-bar chip is a signal now, not a label.** It appears only when at least
  one incident needs a look (`● watchdog 2`), and disappears when everything is fine.
  A permanent "watchdog" with no number told you nothing and cost a status-bar slot;
  the sidebar row remains the always-present door.

## 0.5.0

Review asks from the catalog maintainer, all four closed:

- **A model-authored `check` step can no longer reach the host.** `check` runs an
  argv, so `watchdog_runbooks(action="save")` refuses any playbook containing one —
  it is accepted only from a playbook file the user writes (or a built-in). The
  unattended `on_session_end` path therefore cannot execute model-authored commands.
- **`check` runs with a minimal environment** — `PATH`, `HOME`, `LANG`, plus the
  variables that step names. Provider keys no longer reach the command.
- **Playbook ids are validated** against `^[A-Za-z0-9_-]{1,64}$` (a backslash could
  still escape the folder before).
- **Repo hygiene:** `docs/triage_open_prs.py` and `docs/closed-prs-2026-11-05.md`
  removed — not part of the plugin.

## 0.4.2

- **"Preview only" actually removed.** 0.4.1's edit missed the line (a one-character
  mismatch), so the button survived while the fold-out fix landed — hence a page
  that looked half-updated. Replaced with the one-line explanation under the button.

## 0.4.1

- **"Preview only" removed.** A dry run is the agent's tool (`watchdog_repair` with
  `dry_run`); a second button on the page only asked the operator to choose between
  two things they cannot tell apart.
- **The explainer is a real fold-out.** Its summary sat inside a wrapper, so the
  browser hoisted it and printed a default "Details" label beside it.

## 0.4.0

- **"Checked N ago"** next to the health line, from a stamp the cycle writes — "All
  clear" with no time is unfalsifiable.
- **Repairs are grouped per job** (latest outcome, number of attempts) instead of a
  chronological feed, which is what invited the double-count.
- **"How this works" collapses** behind its own summary: onboarding, not furniture.

## 0.3.x

- 0.3.2: a bare job id is not a name — rows read "A job that no longer exists".
- 0.3.1: removed the duplicated all-clear copy, one line per step, repeated attempts
  collapsed, repairs in plain words (Fixed / Handed to you / Could not fix).
- 0.3.0: numbered how-it-works panel; "Check everything now" / "Preview only".

## 0.3.0

- **A numbered "how this works" panel** on the page: what Watchdog does, why only
  Hermes's own record counts as a repair, and why you only see what it could not
  fix.
- **Plainer controls**: "Check everything now", "Preview only", and an empty state
  that says every scheduled job ran clean.

## 0.2.0

- **A hand-off closes itself after a day.** An incident Watchdog already handed over,
  with no newer failure, is closed in Hermes by the next cycle instead of sitting in
  the counter until someone clicks something.
- **Plain language on the page.** No failure-type jargon, no incident ids in the row:
  the pane says "It was stopped before it finished — the machine slept, or Hermes
  restarted", the header says "1 needs a look", and the buttons are "Fix now" and
  "Hide this".

## 0.1.8

- **An incident already handed over is not escalated again.** Pressing Repair on a
  `needs you` row used to append an identical `escalated` line every time; it now
  reports `already handed to you — Ack it when handled`.
- **The UI tells a stale gateway apart from a refusal.** A `404` on `/ack` now says
  "plugin build is not loaded in the gateway yet — restart the gateway", instead of
  implying the cron store refused.

## 0.1.7

- **An incident whose job was deleted now closes itself.** Core closes an incident
  when its job recovers; a deleted job never recovers, so the incident stayed open
  forever and both Repair and Ack were refused. The cycle detects a missing job
  (paused counts as existing, unreadable job list closes nothing) and closes it
  through core's own ack.

## 0.1.6

- **Ack says why it failed.** `POST /ack` returns core's reason — id not in the
  store, store unavailable, or refused — and the toast shows it. The incident id is
  printed next to the failure-type badge so a report is actionable.

## 0.1.5

- **Ack is on every open incident row**, not only ones that reached `alerted`.
  Closing an incident you have handled should not depend on a state flag.
- `escalated` / `skipped` entries carry `handed_over`, so the toast distinguishes
  "handed to you" from "handed to you, but Hermes refused the record".

## 0.1.4

- **`POST /ack`** closes an incident through core's `ack_incident` — quiet until the
  same error returns.
- Incidents carry their **job name**, and a handed-off row states the next step.

## 0.1.3

- **A budget skip is a hand-off, not silence.** Pressing Repair with the day's
  attempts spent returned no attempts, so the toast said "nothing open, nothing to
  do" while the pane listed an open incident.

## 0.1.2

- **Escalation marks core's incident `alerted`**, and `needs_you` is counted
  separately from `open_incidents`.
- Toasts state what happened: `2 repaired · 1 need you`, `1 to repair, 0 to hand to
  you`, or `nothing open, nothing to do`.

## 0.1.1

- **Sidebar page and nav row** (`/watchdog`). A docked pane only appears in layouts
  that have a right zone, and plugin panes get no ⌘K toggle, so the fleet view was
  unreachable on some layouts.
- The status-bar chip opens the page.

## 0.1.0

- First release: playbook repairs (rerun / pause / check / escalate), verification
  against Hermes's own incident and execution records, a durable attempt ledger with
  a per-incident daily budget, an `on_session_end` hook, three tools, a `/watchdog`
  command, a Desktop pane + chip, and a bundled skill.
