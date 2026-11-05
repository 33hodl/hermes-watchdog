"""Watchdog dashboard backend — mounted at /api/plugins/hermes-watchdog/.

The Desktop pane talks to these routes through ``ctx.rest``. Every route is a thin
wrapper over the same engine the tools and the hook use, so the pane can never
disagree with what the agent sees.

Annotated eagerly (no ``from __future__ import annotations``): the dashboard imports
this file through ``spec_from_file_location``, where Pydantic cannot resolve
stringified annotations, so the ``RepairRequest`` body model must be a real object.
"""

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:  # the engine package lives at the plugin root
    sys.path.insert(0, str(_ROOT))

from hermes_watchdog import ledger, playbooks, repair, sources  # noqa: E402

router = APIRouter()

PLUGIN_ID = "hermes-watchdog"


def _data_dir() -> Optional[Path]:
    try:
        from plugins.plugin_storage import plugin_data_dir
        return plugin_data_dir(PLUGIN_ID)
    except Exception:  # noqa: BLE001 - pane degrades to built-in playbooks only
        return None


class RepairRequest(BaseModel):
    dry_run: bool = Field(False, description="Plan the cycle without running steps.")
    job_id: Optional[str] = Field(None, description="Limit to one cron job id.")


@router.get("/status")
async def status(job_id: Optional[str] = None) -> Dict[str, Any]:
    snap = sources.snapshot(job_id=job_id)
    snap["repairs"] = ledger.summary()
    snap["recent_repairs"] = ledger.recent(limit=10)
    return snap


@router.post("/repair")
async def run_repair(body: RepairRequest) -> Dict[str, Any]:
    return repair.cycle(job_id=body.job_id, dry_run=body.dry_run, data_dir=_data_dir())


@router.get("/runbooks")
async def runbooks() -> Dict[str, Any]:
    return {
        "playbooks": playbooks.all_playbooks(_data_dir()),
        "verbs": list(playbooks.VALID_VERBS),
        "data_dir": str(_data_dir() or ""),
    }
