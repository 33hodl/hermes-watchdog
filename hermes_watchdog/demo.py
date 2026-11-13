"""The demo: one real failure, one real repair, on a throwaway job.

Nothing here is simulated. The demo creates a scheduled job whose script fails the
first time and succeeds the second, lets Hermes record the failure as an incident,
runs the same repair cycle the tools and the hook use, and then deletes the job. The
pane shows the row with a DEMO tag so nobody mistakes it for fleet health.

Why bother: the product's claim ("it fixed something") is invisible on a healthy
machine, and a screenshot of an empty pane sells nothing. A judge, a new user, or an
owner checking the claim can watch the loop run end to end in about two seconds.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from . import ledger, repair

log = logging.getLogger(__name__)

DEMO_JOB_NAME = "Nightly pricing sync (demo)"
DEMO_SCHEDULE = "0 4 * * *"          # never reached: the job is removed at the end
DEMO_PROMPT = "Sync the pricing feed."

_SCRIPT = """#!/usr/bin/env bash
# Hermes Watchdog demo. Fails once, then succeeds — nothing is faked downstream.
STATE="{state}"
if [ ! -f "$STATE" ]; then
  : > "$STATE"
  echo "upstream timed out after 30s while fetching the pricing feed" >&2
  exit 1
fi
echo "pricing feed synced"
"""


def _home() -> Path:
    """The active profile's home, not the one this process was launched with.

    ``os.environ["HERMES_HOME"]`` is pinned when Hermes starts, so a process that
    serves several profiles would write the demo's script into the wrong one.
    ``get_hermes_home`` honours the context-local override first.
    """
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:  # noqa: BLE001 - hosts without core still get a sane path
        base = os.environ.get("HERMES_HOME")
        return Path(base) if base else Path.home() / ".hermes"


def _cron_api(action: str, **kwargs: Any) -> Dict[str, Any]:
    from tools.cronjob_tools import cronjob
    try:
        return json.loads(cronjob(action=action, **kwargs))
    except Exception as exc:  # noqa: BLE001 - the caller reports, never raises
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def _run_sync(job_id: str) -> Dict[str, Any]:
    """Run the job inside this call, so the demo can verify what actually happened."""
    token = None
    try:
        from gateway.session_context import _SESSION_ASYNC_DELIVERY
        token = _SESSION_ASYNC_DELIVERY.set(False)
        return _cron_api("run", job_id=job_id)
    finally:
        if token is not None:
            try:
                _SESSION_ASYNC_DELIVERY.reset(token)
            except Exception:  # noqa: BLE001
                pass


def run(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Create a doomed job, let the watchdog fix it, then tidy up. Returns a report."""
    started = time.time()
    token = uuid.uuid4().hex[:8]
    scripts = _home() / "scripts"
    script_name = f"watchdog-demo-{token}.sh"
    script_path = scripts / script_name
    state_path = _home() / "plugin-data" / "hermes-watchdog" / f"demo-{token}.state"

    report: Dict[str, Any] = {
        "ok": False,
        "job_id": "",
        "job_name": DEMO_JOB_NAME,
        "incident_id": "",
        "outcome": "",
        "detail": "",
        "steps": [],
        "cleaned_up": False,
    }

    try:
        scripts.mkdir(parents=True, exist_ok=True)
        script_path.write_text(_SCRIPT.format(state=str(state_path)), encoding="utf-8")
        script_path.chmod(0o755)

        created = _cron_api(
            "create",
            deliver="local",
            name=DEMO_JOB_NAME,
            no_agent=True,
            prompt=DEMO_PROMPT,
            repeat=3,
            schedule=DEMO_SCHEDULE,
            script=script_name,
        )
        job = created.get("job") or {}
        job_id = str(job.get("job_id") or job.get("id") or "")
        if not created.get("success") or not job_id:
            report["error"] = str(created.get("error") or "could not create the demo job")
            return report
        report["job_id"] = job_id

        # 1. A real failure, recorded by Hermes itself.
        _run_sync(job_id)
        incident_id = _open_incident_for(job_id)
        if not incident_id:
            report["error"] = "the demo job ran but Hermes recorded no incident"
            return report
        report["incident_id"] = incident_id

        # 2. The real repair cycle, scoped to this one job and nothing else.
        cycle = repair.cycle(job_id=job_id, data_dir=data_dir, max_incidents=1)
        attempt = (cycle.get("attempts") or [{}])[0]
        report["outcome"] = attempt.get("outcome") or ("repaired" if cycle.get("repaired") else "")
        report["detail"] = attempt.get("detail") or ""
        report["steps"] = attempt.get("steps") or []
        report["ok"] = report["outcome"] == "repaired"
        if report["outcome"] == "repaired":
            ledger.mark_demo(incident_id)
        if not report["ok"] and not report["detail"]:
            report["error"] = "the cycle recorded no attempt for the demo job"
        return report
    except Exception as exc:  # noqa: BLE001 - the button must always answer
        log.debug("watchdog: demo failed: %s", exc)
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report
    finally:
        # Always leave the machine exactly as it was: no demo job, no demo script.
        if report["job_id"]:
            _cron_api("remove", job_id=report["job_id"])
        for path in (script_path, state_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except Exception as exc:  # noqa: BLE001
                log.debug("watchdog: could not remove %s: %s", path, exc)
        report["cleaned_up"] = not script_path.exists()
        report["took_s"] = round(time.time() - started, 2)


def _open_incident_for(job_id: str) -> str:
    """The incident Hermes just recorded for this job, if it is still open."""
    try:
        from . import sources
        for inc in sources._incidents():  # noqa: SLF001 - read-only view
            if str(inc.get("job_id") or "") != job_id:
                continue
            if str(inc.get("state") or "") in {"detected", "alerted", "open"}:
                return str(inc.get("incident_id") or inc.get("id") or "")
    except Exception as exc:  # noqa: BLE001
        log.debug("watchdog: demo could not read incidents: %s", exc)
    return ""
