"""Read-only views over Hermes's own cron surfaces.

Everything here is defensive: upstream module layout moves between releases, and a
watchdog that crashes because a helper was renamed is worse than one that reports
"upstream unavailable". Every reader returns a plain dict and never raises.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Failure types core already classifies (cron/incidents.py::_classify_failure_type).
FAILURE_TYPES = (
    "rate_limit", "timeout", "auth", "delivery", "config", "script", "agent", "unknown",
)

_OPEN_STATES = ("detected", "alerted")


def _jobs() -> List[Dict[str, Any]]:
    from cron import jobs as _jobs_mod  # late import: survives module moves
    return list(_jobs_mod.list_jobs(include_disabled=False) or [])


def _incidents(state: Optional[str] = None) -> List[Dict[str, Any]]:
    from cron import incidents as _inc
    return list(_inc.list_incidents(state=state) or [])


def _latest_execution(job_id: str) -> Optional[Dict[str, Any]]:
    from cron import executions as _ex
    return _ex.latest_execution(job_id)


def _schedule_text(job: Dict[str, Any]) -> str:
    sched = job.get("schedule")
    if isinstance(sched, dict):
        return str(sched.get("display") or sched.get("expr") or sched.get("kind") or "")
    return str(sched or "")


def job_view(job: Dict[str, Any]) -> Dict[str, Any]:
    """Trim a raw job row down to what the pane and the tools need."""
    return {
        "job_id": job.get("job_id") or job.get("id") or "",
        "name": job.get("name") or "",
        "state": job.get("state") or job.get("status") or "",
        "enabled": not job.get("paused") and not job.get("disabled"),
        "schedule": _schedule_text(job),
        "next_run_at": job.get("next_run_at"),
        "last_run_at": job.get("last_run_at"),
        "last_status": job.get("last_status"),
        "last_error": (job.get("last_error") or "")[:400],
    }


def incident_view(inc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "incident_id": inc.get("id") or inc.get("incident_id") or "",
        "job_id": inc.get("job_id") or "",
        "state": inc.get("state") or "",
        "failure_type": inc.get("failure_type") or "unknown",
        "first_seen_at": inc.get("first_seen_at"),
        "last_seen_at": inc.get("last_seen_at"),
        "error": (inc.get("error") or "")[:500],
    }


def mark_alerted(incident_id: str) -> bool:
    """Record that this incident has been handed to the operator.

    Uses core's own lifecycle (`alerted`), which also restarts its reminder
    cooldown, so a handoff is visible in `hermes cron` rather than living only in
    our ledger. Returns False when core refuses or is unavailable — the caller
    must not claim the handoff happened.
    """
    try:
        from cron import incidents as _inc  # late import
        return bool(_inc.set_incident_state(incident_id, "alerted"))
    except Exception as exc:  # noqa: BLE001
        log.debug("watchdog: could not mark incident %s alerted: %s", incident_id, exc)
        return False


def job_exists(job_id: str) -> Optional[bool]:
    """Does this job still exist (paused counts as existing)? None when unreadable.

    Core closes an incident when its job recovers. A job that was deleted never
    recovers, so its incident would sit open forever unless someone notices.
    """
    try:
        from cron import jobs as _jobs_mod  # late import
        rows = _jobs_mod.list_jobs(include_disabled=True) or []
    except Exception as exc:  # noqa: BLE001
        log.debug("watchdog: job lookup failed: %s", exc)
        return None
    return any((r.get("job_id") or r.get("id")) == job_id for r in rows)


def ack(incident_id: str) -> Tuple[bool, str]:
    """Close an incident the operator has dealt with. Returns (closed, reason).

    Core keeps the signature quiet until the same error returns, so this is how a
    hand-off ends — it is the operator's counterpart to `mark_alerted`. The reason
    is returned rather than swallowed: "it refused" without a why is the kind of
    dead end this plugin is supposed to remove.
    """
    try:
        from cron import incidents as _inc  # late import
    except Exception as exc:  # noqa: BLE001
        return False, f"cron store unavailable: {type(exc).__name__}: {exc}"
    try:
        known = {row.get("id") for row in (_inc.list_incidents() or [])}
    except Exception:  # noqa: BLE001
        known = set()
    if known and incident_id not in known:
        return False, f"incident {incident_id} is not in the cron store (known: {', '.join(sorted(map(str, known))[:3]) or 'none'})"
    try:
        closed = bool(_inc.ack_incident(incident_id))
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return closed, ("closed" if closed else "already closed, missing, or refused by core")


def open_incidents(job_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Incidents core has recorded but not resolved or acked."""
    out: List[Dict[str, Any]] = []
    for inc in _incidents():
        view = incident_view(inc)
        if view["state"] not in _OPEN_STATES:
            continue
        if job_id and view["job_id"] != job_id:
            continue
        out.append(view)
    return out


def job_health(job: Dict[str, Any]) -> str:
    """ok | failing | idle — from the job's own last recorded outcome."""
    status = str(job.get("last_status") or "").lower()
    if status in {"error", "failed", "failure", "timeout"}:
        return "failing"
    if not job.get("last_run_at"):
        return "idle"
    return "ok"



# ── what a person actually needs on an incident ──────────────────────────────
#
# An incident row that says "a failure happened, hide it" is the dead end this
# plugin exists to remove. Every open incident is expanded into four plain parts:
# what happened, what Watchdog already tried, why it stopped, and the exact steps
# (with commands) the operator can take. Wording lives here so it is testable.

_VERB_TEXT = {
    "rerun_job": "ran the job again",
    "pause_job": "paused the job",
    "check": "ran a check",
    "escalate": "handed it to you",
}


def _ago(ts: Optional[str]) -> str:
    """'18h ago' from an ISO stamp, '' when unreadable."""
    if not ts:
        return ""
    try:
        from datetime import datetime, timezone
        when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - when).total_seconds()
    except Exception:  # noqa: BLE001
        return ""
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{int(secs // 60)}m ago"
    if secs < 172800:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def explain_incident(
    inc: Dict[str, Any],
    job: Optional[Dict[str, Any]],
    *,
    last_attempt: Optional[Dict[str, Any]] = None,
    attempts_today: int = 0,
) -> Dict[str, Any]:
    """Four plain-language parts for one open incident.

    ``what`` is what failed and when; ``tried`` lists what Watchdog already did;
    ``why`` says why it stopped instead of trying again; ``steps`` are the concrete
    actions for the operator, each with the command when one exists.
    """
    job_id = str(inc.get("job_id") or "")
    name = str(inc.get("job_name") or job_id or "A scheduled job")
    job_exists = job is not None
    error = str(inc.get("error") or "").strip()
    seen = _ago(inc.get("last_seen_at"))
    output_file = str(inc.get("output_file") or "").strip()

    what = f"{name} failed"
    if seen:
        what += f" ({seen})"
    if error:
        what += f": {error[:240]}"
    else:
        what += ". Hermes stored no error text for it — the run's own output is the only detail."

    tried: List[str] = []
    if last_attempt:
        verbs = [
            _VERB_TEXT.get(v, v)
            for v in str(last_attempt.get("detail") or "").split(",")
            if v.strip()
        ]
        happened = _ago(last_attempt.get("started_at"))
        outcome = str(last_attempt.get("outcome") or "")
        did = ", ".join(verbs) or f"ran the \"{last_attempt.get('playbook') or 'matching'}\" repair"
        line = f"Watchdog {did}"
        if happened:
            line += f" {happened}"
        if outcome == "repaired":
            line += " — it looked fixed, then failed again"
        elif outcome == "escalated":
            line += " — and handed it to you"
        elif outcome == "failed":
            line += " — the repair did not hold"
        tried.append(line)
    if attempts_today:
        tried.append(f"{attempts_today} attempt{'s' if attempts_today != 1 else ''} today for this failure")

    if not job_exists:
        why = "The job this came from has been deleted, so there is nothing left to re-run."
    elif last_attempt and str(last_attempt.get("outcome")) in ("escalated", "failed"):
        why = "Watchdog already tried the repair that matches this failure and it did not hold. Repeating it would fail the same way."
    elif last_attempt is None:
        why = "No repair rule matches this kind of failure, so Watchdog will not guess at a fix."
    else:
        why = "Today's attempts for this failure are used up; trying again would just repeat them."

    steps: List[Dict[str, str]] = []
    if job_exists:
        steps.append({"text": "See what this job does and when it last ran", "command": f"hermes cron show {job_id}"})
        if output_file:
            steps.append({"text": "Read the run's own output — it has the real error",
                          "command": f"tail -n 40 {output_file}"})
        steps.append({"text": "Fix the cause, then run it once by hand", "command": f"hermes cron run {job_id}"})
        steps.append({"text": "Or stop it retrying on its own schedule", "command": f"hermes cron pause {job_id}"})
    steps.append({"text": "Press Ack on this row when you have handled it — it stays quiet until the same error comes back",
                  "command": ""})

    return {"what": what, "tried": tried, "why": why, "steps": steps,
            "output_file": output_file, "job_exists": job_exists,
            "last_seen_at": inc.get("last_seen_at") or ""}

def snapshot(job_id: Optional[str] = None) -> Dict[str, Any]:
    """Full read-only picture: jobs, open incidents, and whether upstream answered.

    ``upstream.ok`` is False when Hermes's cron modules could not be read at all (old
    release, moved module, no cron store yet) — the caller reports that instead of
    inventing an empty fleet.
    """
    errors: List[str] = []
    jobs: List[Dict[str, Any]] = []
    incidents: List[Dict[str, Any]] = []
    try:
        jobs = [_jobs_view_for(j) for j in _jobs()]
    except Exception as exc:  # noqa: BLE001 - read-only diagnostics must never raise
        log.debug("watchdog: cron jobs unavailable: %s", exc)
        errors.append(f"jobs: {exc}")
    try:
        incidents = open_incidents(job_id=job_id)
    except Exception as exc:  # noqa: BLE001
        log.debug("watchdog: cron incidents unavailable: %s", exc)
        errors.append(f"incidents: {exc}")
    names = {j["job_id"]: j["name"] for j in jobs if j.get("name")}
    by_id = {j["job_id"]: j for j in jobs}
    for inc in incidents:
        inc["job_name"] = names.get(inc.get("job_id"), inc.get("job_id", ""))
        try:
            from . import ledger as _ledger
            last = _ledger.last_attempt_for(inc["incident_id"])
            used = _ledger.attempts_today(inc["incident_id"])
        except Exception:  # noqa: BLE001 - the explanation must not block the report
            last, used = None, 0
        inc["detail"] = explain_incident(inc, by_id.get(inc.get("job_id")),
                                         last_attempt=last, attempts_today=used)
    if job_id:
        jobs = [j for j in jobs if j["job_id"] == job_id]

    failing = [j for j in jobs if j["health"] == "failing"]
    if errors and not jobs and not incidents:
        health = "unknown"
    elif incidents or failing:
        health = "degraded" if len(incidents or failing) < 3 else "critical"
    else:
        health = "ok"
    return {
        "health": health,
        "counts": {
            "jobs": len(jobs),
            "failing_jobs": len(failing),
            "open_incidents": len(incidents),
            "needs_you": sum(1 for i in incidents if i.get("state") == "alerted"),
        },
        "jobs": jobs,
        "incidents": incidents,
        "upstream": {"ok": not errors, "errors": errors},
    }


def _jobs_view_for(job: Dict[str, Any]) -> Dict[str, Any]:
    view = job_view(job)
    view["health"] = job_health(job)
    return view
