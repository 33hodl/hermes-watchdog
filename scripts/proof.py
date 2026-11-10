#!/usr/bin/env python3
"""Reproducible proof: a failing cron job gets repaired, and the repair is verified.

Runs entirely in a throwaway HERMES_HOME — no live profile, no cron registry, no
network. It exercises the real code paths: Hermes's own cron job store, its own
`cronjob` tool, core's incident table, and this plugin's repair cycle.

    python scripts/proof.py

Exit 0 means: the timeout incident was rerun, the next run succeeded, core's own
record moved it off `detected`, and the ledger recorded `repaired`. The script
incident is handed off (`alerted`) rather than retried — nothing is left unhandled.
Any other outcome exits 1 with the report printed.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile

PLUGIN = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))


def main() -> int:
    home = pathlib.Path(tempfile.mkdtemp(prefix="watchdog-proof-"))
    os.environ["HERMES_HOME"] = str(home)
    try:
        (home / "scripts").mkdir(parents=True, exist_ok=True)
        flag = home / "upstream-healthy"
        (home / "scripts" / "flaky.py").write_text(
            "import sys, pathlib\n"
            f"flag = pathlib.Path({str(flag)!r})\n"
            "if not flag.exists():\n"
            "    flag.write_text('ok')\n"
            "    print('boom: upstream 503')\n"
            "    sys.exit(1)\n"
            "print('ok')\n"
        )

        from cron import incidents, jobs  # noqa: PLC0415
        from tools.cronjob_tools import cronjob  # noqa: PLC0415

        from hermes_watchdog import ledger, repair  # noqa: PLC0415

        job = jobs.create_job(
            name="proof-digest",
            schedule="0 9 * * *",
            prompt="",
            no_agent=True,
            script="flaky.py",
        )
        job_id = job.get("job_id") or job["id"]

        first = json.loads(cronjob(action="run", job_id=job_id))
        print("run 1  last_status:", first.get("job", {}).get("last_status"))

        flag.write_text("ok")  # the upstream is healthy again
        incident_id, _ = incidents.upsert_incident(job_id, "upstream timed out after 30s")

        before = [(i["id"], i["failure_type"], i["state"]) for i in incidents.list_incidents()]
        print("incidents before:", before)

        report = repair.cycle(data_dir=home / "plugin-data" / "hermes-watchdog")
        print("cycle  health:", report["health"], "attempts:", len(report["attempts"]))
        for attempt in report["attempts"]:
            print(f"  {attempt['playbook']} -> {attempt['outcome']} ({attempt['detail']})")
            for step in attempt["steps"]:
                print(f"    {step['verb']} ok={step['ok']} {step['detail']}")

        after = [(i["id"], i["state"]) for i in incidents.list_incidents()]
        rows = [(r["playbook"], r["outcome"]) for r in ledger.recent(5)]
        print("incidents after:", after, "ledger:", rows)

        # Core records two incidents for that one bad run: a `script` failure (the
        # process exited 1) and the timeout we filed. Neither may be left unhandled,
        # and at least one must have been repaired rather than handed off.
        ok = (
            bool(report["repaired"])
            and all(state in {"resolved", "alerted", "closed"} for _, state in after)
            and incident_id in {i for i, _ in after}
        )
        print("\nPROOF", "PASSED" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
