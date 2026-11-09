# Why the verification is the product

Most cron watchers do the same thing: notice a failure, send a message. The
message is where they stop, and that is the part that does not work. A job that
failed on a transient timeout gets retried by a human days later, and a job that
failed for a real reason gets pinged every day until someone turns it off.

The interesting problem is not detection. It is knowing whether a repair worked.

## The rule

A repair counts as `repaired` only when Hermes's own record agrees:

1. the incident left the open states (`detected`, `alerted`) because core saw the
   job recover, or
2. the job's latest execution finished successfully after the attempt started.

Nothing else counts. Steps that ran and exited zero, a rerun that was merely
accepted, a process that reported success — all of those are `failed` unless one
of the two conditions above holds. The ledger stores the outcome, so a wrong
repair is visible after the fact instead of being buried in a log line.

That single rule is what makes the plugin safe to leave running: you are not
trusting "I tried", you are trusting the same record that decides whether the job
is healthy.

## What that buys

- **Silence is information.** When nothing arrives, it means the next run
  succeeded. Before, silence meant nobody had looked yet.
- **Escalation is rare and specific.** Only failures no playbook can touch reach
  a human, and they arrive with the failure, the playbook that matched, the steps
  it ran, and what is left to decide.
- **Loops cannot form.** Each incident carries a per-playbook daily attempt budget
  that is checked before any step runs. A repair that would loop stops itself and
  escalates instead.
- **The blast radius is bounded.** The only verbs are `rerun_job`, `pause_job`,
  `check` (an argv list from a playbook the user wrote, no shell, one timeout) and
  `escalate`. There is no arbitrary shell, no prompt rewriting, no schedule edits.

## Deliberate non-goals

- Not a metrics or alerting product: it does not page you, aggregate, or chart.
- Not a scheduler: it never creates, edits or reschedules jobs.
- Not a model feature: the matching is deterministic. A playbook either matches a
  failure type, an error substring, a job name or a job id, or it does not.
