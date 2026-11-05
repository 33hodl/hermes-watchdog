"""Playbooks: what to *do* about a failure, not just how to describe it.

A playbook is a small declarative record:

    {
      "id": "rerun-on-timeout",
      "match": {"failure_type": "timeout"},        # any subset of failure_type /
                                                   # error_contains / job_name_contains /
                                                   # job_id
      "steps": [{"verb": "rerun_job"}],
      "max_attempts_per_day": 3,
      "escalate_on_fail": true
    }

Supported verbs (all bounded, all reversible):

``rerun_job``   Fire the failing job now through Hermes's own cron API.
``pause_job``   Pause the job so it stops burning the schedule while broken.
``check``       Run an argv list (no shell) and require exit 0. This is how a
                playbook proves the cause is gone before calling itself done.
``escalate``    Stop and hand the incident to the operator. Always implied when
                a repair fails and ``escalate_on_fail`` is true.

Playbooks live in ``<plugin data dir>/playbooks/*.json`` — one playbook per file,
written by the user or the agent. Built-ins cover the failure types core already
classifies and are deliberately timid: rerun once where a rerun is plausibly the
fix, escalate where it is not. User playbooks win over built-ins on an equal
match.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

MAX_STEPS = 6
VALID_VERBS = ("rerun_job", "pause_job", "check", "escalate")

BUILTIN_PLAYBOOKS: List[Dict[str, Any]] = [
    {
        "id": "builtin-rerun-timeout",
        "source": "builtin",
        "description": "Timeouts are usually transient on a loaded host: rerun once.",
        "match": {"failure_type": "timeout"},
        "steps": [{"verb": "rerun_job"}],
        "max_attempts_per_day": 3,
        "escalate_on_fail": True,
    },
    {
        "id": "builtin-rerun-delivery",
        "source": "builtin",
        "description": "A delivery failure is the message, not the work: rerun the job.",
        "match": {"failure_type": "delivery"},
        "steps": [{"verb": "rerun_job"}],
        "max_attempts_per_day": 2,
        "escalate_on_fail": True,
    },
    {
        "id": "builtin-rerun-agent",
        "source": "builtin",
        "description": "Model/provider hiccups: one clean rerun usually lands.",
        "match": {"failure_type": "agent"},
        "steps": [{"verb": "rerun_job"}],
        "max_attempts_per_day": 2,
        "escalate_on_fail": True,
    },
    {
        "id": "builtin-escalate-auth",
        "source": "builtin",
        "description": "Credentials do not fix themselves; a human has to re-auth.",
        "match": {"failure_type": "auth"},
        "steps": [{"verb": "escalate"}],
        "max_attempts_per_day": 1,
        "escalate_on_fail": True,
    },
    {
        "id": "builtin-escalate-config",
        "source": "builtin",
        "description": "A config/validation failure needs a decision, not a retry.",
        "match": {"failure_type": "config"},
        "steps": [{"verb": "escalate"}],
        "max_attempts_per_day": 1,
        "escalate_on_fail": True,
    },
    {
        "id": "builtin-escalate-script",
        "source": "builtin",
        "description": "A broken scheduler script will fail identically every run: pause it and ask.",
        "match": {"failure_type": "script"},
        "steps": [{"verb": "pause_job"}, {"verb": "escalate"}],
        "max_attempts_per_day": 1,
        "escalate_on_fail": True,
    },
    {
        "id": "builtin-escalate-unknown",
        "source": "builtin",
        "description": "Unrecognised failure: never guess at a repair.",
        "match": {},
        "steps": [{"verb": "escalate"}],
        "max_attempts_per_day": 1,
        "escalate_on_fail": True,
    },
]


def _normalize(raw: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    """Validate one playbook; return None (and log) when it isn't usable."""
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get("id") or "").strip()
    if not pid:
        return None
    match = raw.get("match") if isinstance(raw.get("match"), dict) else {}
    steps_in = raw.get("steps") if isinstance(raw.get("steps"), list) else []
    steps: List[Dict[str, Any]] = []
    for step in steps_in:
        if not isinstance(step, dict):
            continue
        verb = str(step.get("verb") or "")
        if verb not in VALID_VERBS:
            log.warning("watchdog: playbook %s step %r has unknown verb; skipped", pid, verb)
            continue
        clean: Dict[str, Any] = {"verb": verb}
        if verb == "check":
            argv = step.get("argv")
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
                log.warning("watchdog: playbook %s check step needs an argv list; skipped", pid)
                continue
            clean["argv"] = argv[:16]
            try:
                clean["timeout"] = max(1.0, min(float(step.get("timeout", 30)), 120.0))
            except (TypeError, ValueError):
                clean["timeout"] = 30.0
        if len(steps) < MAX_STEPS:
            steps.append(clean)
    if not steps:
        return None
    try:
        budget = max(0, min(int(raw.get("max_attempts_per_day", 3)), 50))
    except (TypeError, ValueError):
        budget = 3
    return {
        "id": pid,
        "source": source,
        "description": str(raw.get("description") or ""),
        "match": {k: v for k, v in match.items() if isinstance(v, str) and v},
        "steps": steps,
        "max_attempts_per_day": budget,
        "escalate_on_fail": bool(raw.get("escalate_on_fail", True)),
    }


def load_user_playbooks(data_dir: Optional[Path]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if data_dir is None:
        return out
    root = Path(data_dir) / "playbooks"
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - a bad file must not break the cycle
            log.warning("watchdog: bad playbook %s: %s", path.name, exc)
            continue
        items = raw if isinstance(raw, list) else [raw]
        for item in items:
            norm = _normalize(item, f"user:{path.name}")
            if norm is not None:
                out.append(norm)
    return out


def all_playbooks(data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """User playbooks first (they win), then the built-ins."""
    users = load_user_playbooks(data_dir)
    builtins = [_normalize(p, "builtin") for p in BUILTIN_PLAYBOOKS]
    return users + [p for p in builtins if p is not None]


def match_playbook(
    incident: Dict[str, Any], playbooks: List[Dict[str, Any]], job_name: str = "",
) -> Optional[Dict[str, Any]]:
    """Pick the most specific playbook for one incident.

    Specificity = number of match keys that fired; user playbooks are tried before
    built-ins at equal specificity, and the empty-match built-in is the last resort.
    """
    ftype = str(incident.get("failure_type") or "unknown")
    error = str(incident.get("error") or "").lower()
    best: Optional[Dict[str, Any]] = None
    best_score = -1
    for pb in playbooks:
        match = pb.get("match") or {}
        score = 0
        ok = True
        if "failure_type" in match:
            if match["failure_type"] != ftype:
                ok = False
            else:
                score += 2
        if ok and "error_contains" in match:
            if match["error_contains"].lower() not in error:
                ok = False
            else:
                score += 1
        if ok and "job_name_contains" in match:
            if match["job_name_contains"].lower() not in (job_name or "").lower():
                ok = False
            else:
                score += 1
        if ok and "job_id" in match:
            if match["job_id"] != incident.get("job_id"):
                ok = False
            else:
                score += 1
        if not ok:
            continue
        if score > best_score:
            best, best_score = pb, score
    return best
