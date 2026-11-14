"""Hand an incident to the agent, so the user never has to read a command.

The page's primary action is "Ask Hermes to fix it": this builds a prompt with the
context Watchdog already has and fires the failing job through Hermes's own cron
tool with that prompt as transient per-fire context. The agent then diagnoses the
real cause inside a normal turn, and its answer re-enters the conversation. No new
tool surface, no shell of our own.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def build_prompt(incident: Dict[str, Any], job: Optional[Dict[str, Any]] = None) -> str:
    """The instruction the agent receives. Written for a fix, not a re-run."""
    name = str(incident.get("job_name") or incident.get("job_id") or "a scheduled job")
    job_id = str(incident.get("job_id") or "")
    error = str(incident.get("error") or "").strip()
    when = str(incident.get("last_seen_at") or "")
    output_file = str(incident.get("output_file") or "").strip()
    self_check = "sweep" in name.lower() or "watchdog" in name.lower()

    lines = [
        f"The scheduled job \"{name}\" ({job_id}) failed" + (f" at {when}." if when else "."),
    ]
    if error:
        lines.append(f"Hermes recorded this failure: {error}")
    else:
        lines.append("Hermes stored no error text for the failure.")
    if output_file:
        lines.append(f"The run's own output is at {output_file} — read it before deciding anything.")
    if self_check:
        lines.append(
            "This is Hermes Watchdog's own check job, not one of the user's jobs. Confirm it is "
            "healthy now (a Hermes restart is the usual cause) and close the incident if so."
        )
    else:
        lines += [
            "Find the actual cause and fix it — do not simply re-run the job and declare success.",
            "If it cannot be fixed from here, say plainly what a person must change.",
        ]
    lines.append(
        "When you are done, reply with two or three sentences the user can act on: what was wrong, "
        "what you changed, and what happens next. No command snippets unless they are unavoidable."
    )
    return "\n".join(lines)


def hand_off(incident: Dict[str, Any], job: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fire the failing job once, with the diagnose-and-fix prompt attached."""
    job_id = str(incident.get("job_id") or "")
    if not job_id:
        return {"ok": False, "error": "this incident has no job left to run"}
    prompt = build_prompt(incident, job)
    try:
        from tools.cronjob_tools import cronjob
        raw = cronjob(action="run", job_id=job_id, prompt=prompt)
        result = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception as exc:  # noqa: BLE001 - report, never raise
        log.debug("watchdog: hand-off failed: %s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if not result.get("success"):
        return {"ok": False, "error": str(result.get("error") or "Hermes refused the run")}
    return {"ok": True, "job_id": job_id, "started": True}
