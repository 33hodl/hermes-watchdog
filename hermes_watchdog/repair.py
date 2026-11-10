"""The repair cycle: observe -> match -> act (bounded) -> verify -> record.

One cycle never invents work. It only touches incidents Hermes already recorded as
open, runs at most one playbook per incident, and stops inside a hard budget so a
watchdog can never itself become the runaway job.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from typing import Any, Dict, List, Optional

from . import ledger, playbooks, sources

log = logging.getLogger(__name__)

MAX_JOBS_PER_CYCLE = 5          # hard cap on incidents touched in one cycle
MAX_CYCLE_SECONDS = 120.0       # whole-cycle wall clock budget


def _cron_api(action: str, job_id: str) -> Dict[str, Any]:
    """Hermes's own cron tool — same path the CLI's ``hermes cron run`` uses."""
    from tools.cronjob_tools import cronjob
    try:
        return json.loads(cronjob(action=action, job_id=job_id))
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def _run_step(step: Dict[str, Any], job_id: str) -> Dict[str, Any]:
    """Execute one playbook step. Never raises; returns a step record."""
    verb = step.get("verb")
    if verb == "rerun_job":
        result = _cron_api("run", job_id)
        return {
            "verb": verb,
            "ok": bool(result.get("success", True)),
            "detail": str(result.get("error") or result.get("message") or "rerun requested")[:300],
        }
    if verb == "pause_job":
        result = _cron_api("pause", job_id)
        return {
            "verb": verb,
            "ok": bool(result.get("success", True)),
            "detail": str(result.get("error") or "paused")[:300],
        }
    if verb == "check":
        argv: List[str] = list(step.get("argv") or [])
        timeout = float(step.get("timeout") or 30)
        try:
            proc = subprocess.run(  # noqa: S603 - argv list, no shell, authored by the user
                argv, capture_output=True, text=True, timeout=timeout, check=False,
            )
            tail = (proc.stdout or proc.stderr or "").strip().splitlines()
            return {
                "verb": verb,
                "ok": proc.returncode == 0,
                "detail": f"exit {proc.returncode}" + (f": {tail[-1][:200]}" if tail else ""),
            }
        except FileNotFoundError:
            return {"verb": verb, "ok": False, "detail": f"command not found: {argv[0] if argv else ''}"}
        except subprocess.TimeoutExpired:
            return {"verb": verb, "ok": False, "detail": f"check timed out after {timeout:.0f}s"}
        except Exception as exc:  # noqa: BLE001
            return {"verb": verb, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    if verb == "escalate":
        return {"verb": verb, "ok": True, "detail": "escalated to operator"}
    return {"verb": str(verb), "ok": False, "detail": "unknown verb"}


def _verified(job_id: str, incident_id: str, started_at: float) -> bool:
    """Did the failure actually stop? Core's own record is the only authority.

    Primary signal: the incident left the open states (core resolves it when the job
    recovers). Secondary: the job's latest execution finished successfully after this
    attempt started. Nothing else counts as a repair.
    """
    try:
        for inc in sources._incidents():  # noqa: SLF001 - read-only view
            if (inc.get("id") or inc.get("incident_id")) != incident_id:
                continue
            if str(inc.get("state")) in {"resolved", "closed"}:
                return True
            break
    except Exception as exc:  # noqa: BLE001
        log.debug("watchdog: verify via incidents failed: %s", exc)
    try:
        latest = sources._latest_execution(job_id)  # noqa: SLF001
        if latest and str(latest.get("status")) in {"success", "completed", "ok"}:
            finished = latest.get("finished_at") or latest.get("started_at") or ""
            if _ts(finished) >= started_at - 1:
                return True
    except Exception as exc:  # noqa: BLE001
        log.debug("watchdog: verify via executions failed: %s", exc)
    return False


def _ts(value: Any) -> float:
    """Best-effort ISO-8601 -> epoch; 0.0 when unparseable."""
    if not value:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        from datetime import datetime, timezone
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text).astimezone(timezone.utc).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def cycle(
    job_id: Optional[str] = None,
    dry_run: bool = False,
    data_dir=None,
    max_incidents: int = MAX_JOBS_PER_CYCLE,
) -> Dict[str, Any]:
    """Run one repair cycle. Returns a report the tools, pane and digest all share."""
    started = time.time()
    snap = sources.snapshot(job_id=job_id)
    books = playbooks.all_playbooks(data_dir)
    names = {j["job_id"]: j["name"] for j in snap["jobs"]}
    report: Dict[str, Any] = {
        "dry_run": dry_run,
        "health": snap["health"],
        "counts": snap["counts"],
        "upstream": snap["upstream"],
        "repaired": [],
        "failed": [],
        "escalated": [],
        "skipped": [],
        "stale": [],
        "attempts": [],
    }

    incidents = snap["incidents"][: max(1, min(int(max_incidents), 50))]
    for inc in incidents:
        if time.time() - started > MAX_CYCLE_SECONDS:
            report["skipped"].append({"incident_id": inc["incident_id"], "reason": "cycle budget spent"})
            continue
        job = inc["job_id"]
        name = names.get(job, job)
        if sources.job_exists(job) is False:
            # Nothing to repair and nothing will ever recover it: the job is gone.
            closed, reason = sources.ack(inc["incident_id"])
            report["stale"].append({
                "incident_id": inc["incident_id"],
                "job_id": job,
                "job_name": name,
                "closed": closed,
                "reason": "job no longer exists" + ("" if closed else f" — could not close: {reason}"),
            })
            continue
        book = playbooks.match_playbook(inc, books, job_name=name)
        if book is None:
            handed = sources.mark_alerted(inc["incident_id"])
            report["escalated"].append(
                {"incident_id": inc["incident_id"], "job_name": name, "handed_over": handed,
                 "job_id": job, "reason": "no playbook matched"},
            )
            continue
        used = ledger.attempts_today(inc["incident_id"])
        if used >= book["max_attempts_per_day"]:
            # Out of attempts for today: core must say "needs you", not stay quiet
            # while the pane still shows an open incident.
            handed = sources.mark_alerted(inc["incident_id"])
            report["skipped"].append({
                "incident_id": inc["incident_id"],
                "job_name": name,
                "job_id": job,
                "handed_over": handed,
                "reason": f"daily limit reached ({used}/{book['max_attempts_per_day']} today)",
            })
            continue
        if dry_run:
            report["attempts"].append({
                "incident_id": inc["incident_id"],
                "job_name": name,
                "playbook": book["id"],
                "steps": [s["verb"] for s in book["steps"]],
                "outcome": "planned",
            })
            continue

        repair_id = ledger.start_attempt(
            inc["incident_id"], job, name, book["id"], book.get("source", ""),
        )
        step_records: List[Dict[str, Any]] = []
        escalated = False
        for step in book["steps"]:
            if time.time() - started > MAX_CYCLE_SECONDS:
                step_records.append({"verb": step["verb"], "ok": False, "detail": "cycle budget spent"})
                break
            rec = _run_step(step, job)
            step_records.append(rec)
            if step["verb"] == "escalate":
                escalated = True
                break
            if not rec["ok"]:
                break

        if escalated:
            handed = sources.mark_alerted(inc["incident_id"])
            outcome = "escalated"
            detail = ("handed to the operator (core incident marked alerted)" if handed
                      else "handed to the operator (core did not accept the state change)")
        elif step_records and all(r["ok"] for r in step_records):
            ok = _verified(job, inc["incident_id"], started)
            outcome, detail = ("repaired", "verified by Hermes's own incident/execution record") if ok \
                else ("failed", "steps ran but the failure is still open")
        else:
            outcome, detail = "failed", "a step failed"
        ledger.finish_attempt(repair_id, outcome, detail)

        entry = {
            "incident_id": inc["incident_id"],
            "job_id": job,
            "job_name": name,
            "playbook": book["id"],
            "steps": step_records,
            "outcome": outcome,
            "detail": detail,
        }
        report["attempts"].append(entry)
        report["repaired" if outcome == "repaired" else
               ("escalated" if outcome == "escalated" else "failed")].append(entry)

    report["duration_s"] = round(time.time() - started, 2)
    return report
