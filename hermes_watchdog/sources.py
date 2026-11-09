"""Read-only views over Hermes's own cron surfaces.

Everything here is defensive: upstream module layout moves between releases, and a
watchdog that crashes because a helper was renamed is worse than one that reports
"upstream unavailable". Every reader returns a plain dict and never raises.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

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
