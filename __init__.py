"""hermes-watchdog — cron jobs that fix themselves.

Three surfaces, one engine:

* tools — ``watchdog_status`` / ``watchdog_repair`` / ``watchdog_runbooks``
* hook — ``on_session_end``: when a *cron* turn fails, repair that job in place
  before the operator ever sees a repeat failure ping
* Desktop — a Watchdog pane + status chip over the same report
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)

PLUGIN_ID = "hermes-watchdog"
_HERE = Path(__file__).resolve().parent


def _data_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir
    return plugin_data_dir(PLUGIN_ID)


def _json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


# --- tools ------------------------------------------------------------------

def _status(args: Dict[str, Any], **_: Any) -> str:
    from .hermes_watchdog import ledger, sources
    job_id = args.get("job_id") or None
    snap = sources.snapshot(job_id=job_id)
    snap["repairs"] = ledger.summary()
    snap["recent_repairs"] = ledger.recent(limit=8)
    return _json({"success": True, "status": snap})


def _repair(args: Dict[str, Any], **_: Any) -> str:
    from .hermes_watchdog import repair
    report = repair.cycle(
        job_id=args.get("job_id") or None,
        dry_run=bool(args.get("dry_run")),
        data_dir=_data_dir(),
    )
    return _json({"success": True, "report": report})


def _runbooks(args: Dict[str, Any], **_: Any) -> str:
    from .hermes_watchdog import playbooks
    action = str(args.get("action") or "list")
    data_dir = _data_dir()
    if action == "save":
        raw = args.get("playbook")
        if not isinstance(raw, dict):
            return _json({"success": False, "error": "playbook must be a JSON object"})
        pid = str(raw.get("id") or "").strip()
        if not pid or "/" in pid or ".." in pid:
            return _json({"success": False, "error": "playbook needs a simple 'id'"})
        folder = data_dir / "playbooks"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{pid}.json"
        path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        return _json({"success": True, "saved": str(path)})
    return _json({
        "success": True,
        "data_dir": str(data_dir / "playbooks"),
        "playbooks": playbooks.all_playbooks(data_dir),
        "verbs": list(playbooks.VALID_VERBS),
    })


_STATUS_SCHEMA = {
    "name": "watchdog_status",
    "description": (
        "Cron fleet health from Hermes's own records: jobs with their last outcome, open "
        "cron incidents (id, failure type, error), and the watchdog repair ledger."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Limit to one cron job id."},
        },
        "required": [],
    },
}

_REPAIR_SCHEMA = {
    "name": "watchdog_repair",
    "description": (
        "Run one bounded repair cycle: match each open cron incident to a playbook, run its "
        "steps (rerun_job / pause_job / check / escalate), then verify the failure actually "
        "cleared against Hermes's own incident and execution records. Respects each "
        "playbook's daily attempt budget."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dry_run": {"type": "boolean", "description": "Plan only: say what would run."},
            "job_id": {"type": "string", "description": "Limit the cycle to one cron job id."},
        },
        "required": [],
    },
}

_RUNBOOKS_SCHEMA = {
    "name": "watchdog_runbooks",
    "description": (
        "List the repair playbooks in force (user-defined + built-in) with their match rules "
        "and steps, or save a new one. A playbook's 'check' step runs an argv list, so a saved "
        "playbook executes commands on this machine."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "save"], "description": "Default: list."},
            "playbook": {
                "type": "object",
                "description": (
                    "For action=save: {id, match:{failure_type|error_contains|job_name_contains|"
                    "job_id}, steps:[{verb:'rerun_job'|'pause_job'|'check'|'escalate', argv?, "
                    "timeout?}], max_attempts_per_day?, escalate_on_fail?}"
                ),
            },
        },
        "required": [],
    },
}


# --- hook -------------------------------------------------------------------

def _on_session_end(*, failed: bool = False, interrupted: bool = False, **kwargs: Any) -> None:
    """A cron turn failed — try its playbook now, while the context is still fresh.

    Deliberately narrow: only inside a cron execution, only on a real failure, bounded
    to that one job, and every error swallowed. The operator-visible path is the
    ``watchdog_repair`` tool and the pane; this hook exists so a self-healing run does
    not have to wait for the next scheduler tick.
    """
    if not failed or interrupted:
        return
    try:
        from cron.execution_identity import current_cron_execution
        execution = current_cron_execution()
        if execution is None:
            return
        job_id = getattr(execution, "job_id", None) or getattr(execution, "job", None)
        if not job_id:
            return
        from .hermes_watchdog import repair
        report = repair.cycle(job_id=str(job_id), data_dir=_data_dir(), max_incidents=1)
        log.info(
            "watchdog: in-run repair for %s — repaired=%d failed=%d escalated=%d",
            job_id, len(report["repaired"]), len(report["failed"]), len(report["escalated"]),
        )
    except Exception as exc:  # noqa: BLE001 - a hook must never break the turn
        log.debug("watchdog: hook skipped: %s", exc)


# --- slash command ----------------------------------------------------------

def _watchdog_command(raw_args: str = ""):
    from .hermes_watchdog import repair, sources
    arg = (raw_args or "").strip()
    if arg in {"repair", "fix", "run"}:
        report = repair.cycle(data_dir=_data_dir())
        lines = [f"watchdog: {report['health']} — repaired {len(report['repaired'])}, "
                 f"failed {len(report['failed'])}, escalated {len(report['escalated'])}"]
        for item in report["repaired"]:
            lines.append(f"  ✓ {item['job_name']} — {item['playbook']} ({item['detail']})")
        for item in report["failed"]:
            lines.append(f"  ✗ {item['job_name']} — {item['playbook']} ({item['detail']})")
        for item in report["escalated"]:
            lines.append(f"  ! {item['job_name']} — needs you ({item.get('reason') or item.get('detail')})")
        return "\n".join(lines)
    snap = sources.snapshot()
    lines = [f"watchdog: {snap['health']} — {snap['counts']['jobs']} jobs, "
             f"{snap['counts']['open_incidents']} open incidents"]
    for inc in snap["incidents"][:10]:
        lines.append(f"  · {inc['failure_type']}: {inc['job_id']} — {inc['error'][:100]}")
    if not snap["incidents"]:
        lines.append("  nothing failing")
    lines.append("  `/watchdog repair` runs the playbooks")
    return "\n".join(lines)


def register(ctx) -> None:
    ctx.register_tool(
        name="watchdog_status", toolset="watchdog", schema=_STATUS_SCHEMA,
        handler=_status, description="Cron fleet health and open incidents.",
        emoji="🐕",
    )
    ctx.register_tool(
        name="watchdog_repair", toolset="watchdog", schema=_REPAIR_SCHEMA,
        handler=_repair, description="Run a bounded, verified repair cycle.",
        emoji="🔧",
    )
    ctx.register_tool(
        name="watchdog_runbooks", toolset="watchdog", schema=_RUNBOOKS_SCHEMA,
        handler=_runbooks, description="List or save repair playbooks.",
        emoji="📕",
    )
    ctx.register_hook("on_session_end", _on_session_end)
    try:
        ctx.register_command(
            "watchdog", _watchdog_command,
            description="Cron health and self-healing repairs",
            args_hint="[repair]",
        )
    except Exception as exc:  # noqa: BLE001 - a slash command is a bonus, not the point
        log.debug("watchdog: slash command unavailable: %s", exc)
    try:
        ctx.register_skill(
            "watchdog",
            _HERE / "skills" / "watchdog" / "SKILL.md",
            description="Operate the watchdog: read the fleet, author playbooks, verify repairs.",
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("watchdog: bundled skill not registered: %s", exc)
