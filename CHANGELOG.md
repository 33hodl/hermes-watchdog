# Changelog

Everything here was found by running the plugin on a real Desktop client, not by
reading the code. Each fix is one behaviour that made a click look like a no-op.

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
