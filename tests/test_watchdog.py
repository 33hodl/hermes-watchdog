"""Unit tests for the watchdog engine (stdlib unittest — no pytest needed).

Run from the plugin root:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermes_watchdog import playbooks, repair, sources  # noqa: E402


def _incident(ftype="timeout", job_id="job-1", error="upstream timed out after 30s", state="detected"):
    return {
        "incident_id": "inc-1", "job_id": job_id, "state": state, "failure_type": ftype,
        "error": error, "first_seen_at": "2026-11-05T00:00:00Z", "last_seen_at": "2026-11-05T01:00:00Z",
    }


def _jobs(job_id="job-1", status="error"):
    return {
        "health": "degraded",
        "counts": {"jobs": 1, "failing_jobs": 1, "open_incidents": 1},
        "jobs": [{
            "job_id": job_id, "name": "daily-digest", "state": "active", "enabled": True,
            "schedule": "0 9 * * *", "next_run_at": None, "last_run_at": "2026-11-05T01:00:00Z",
            "last_status": status, "last_error": "boom", "health": "failing",
        }],
        "incidents": [_incident(job_id=job_id)],
        "upstream": {"ok": True, "errors": []},
    }


class _FakeLedger(SimpleNamespace):
    def __init__(self, used=0):
        super().__init__()
        self.used = used
        self.rows = []
        self.finish_attempt = lambda rid, outcome, detail="": self.rows.append((outcome, detail))
        self.attempts_today = lambda incident_id: self.used
        self.start_attempt = lambda *a, **kw: 1


class PlaybookTests(unittest.TestCase):
    def test_builtins_ship_and_cover_unknown(self):
        books = playbooks.all_playbooks(None)
        ids = {b["id"] for b in books}
        self.assertIn("builtin-rerun-timeout", ids)
        self.assertIn("builtin-escalate-unknown", ids)

    def test_timeout_matches_rerun_not_pause(self):
        books = playbooks.all_playbooks(None)
        book = playbooks.match_playbook(_incident("timeout"), books, job_name="daily-digest")
        self.assertEqual(book["id"], "builtin-rerun-timeout")
        self.assertEqual([s["verb"] for s in book["steps"]], ["rerun_job"])

    def test_auth_escalates(self):
        books = playbooks.all_playbooks(None)
        book = playbooks.match_playbook(_incident("auth", error="401 unauthorized"), books)
        self.assertEqual([s["verb"] for s in book["steps"]], ["escalate"])

    def test_empty_match_is_last_resort(self):
        books = playbooks.all_playbooks(None)
        book = playbooks.match_playbook(_incident("weird-type"), books)
        self.assertEqual(book["id"], "builtin-escalate-unknown")

    def test_bad_steps_are_dropped_not_guessed(self):
        raw = {"id": "x", "steps": [{"verb": "nuke"}, {"verb": "check", "argv": "curl"}, {"verb": "rerun_job"}]}
        norm = playbooks._normalize(raw, "user:test.json")
        self.assertEqual([s["verb"] for s in norm["steps"]], ["rerun_job"])

    def test_playbook_with_no_valid_steps_is_rejected(self):
        self.assertIsNone(playbooks._normalize({"id": "x", "steps": [{"verb": "nuke"}]}, "user:t.json"))


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.fake_ledger = _FakeLedger()

    def _run(self, verified, api=None, **kw):
        calls = []

        def _api(action, job_id):
            calls.append((action, job_id))
            return api(action, job_id) if api else {"success": True}

        with patch.object(repair, "sources") as s, patch.object(repair, "ledger", self.fake_ledger), \
                patch.object(repair, "_cron_api", _api), patch.object(repair, "_verified", lambda *a: verified):
            s.snapshot.return_value = _jobs(**kw)
            report = repair.cycle(data_dir=None)
        return report, calls

    def test_verified_repair_is_reported_as_repaired(self):
        report, calls = self._run(True)
        self.assertEqual(len(report["repaired"]), 1)
        self.assertEqual(calls, [("run", "job-1")])
        self.assertEqual(self.fake_ledger.rows[0][0], "repaired")

    def test_unverified_repair_is_a_failure_not_a_success(self):
        report, _ = self._run(False)
        self.assertEqual(report["repaired"], [])
        self.assertEqual(len(report["failed"]), 1)
        self.assertEqual(self.fake_ledger.rows[0][0], "failed")

    def test_budget_exhausted_skips_without_running(self):
        self.fake_ledger.used = 99
        report, calls = self._run(True)
        self.assertEqual(calls, [])
        self.assertEqual(len(report["skipped"]), 1)
        self.assertIn("daily limit", report["skipped"][0]["reason"])

    def test_dry_run_touches_nothing(self):
        report, calls = self._run(True)
        dry, calls_dry = self._run(True)
        self.assertEqual(calls_dry, [("run", "job-1")])

        with patch.object(repair, "sources") as s, patch.object(repair, "ledger", _FakeLedger()), \
                patch.object(repair, "_cron_api", lambda a, j: (_ for _ in ()).throw(AssertionError("ran"))):
            s.snapshot.return_value = _jobs()
            plan = repair.cycle(data_dir=None, dry_run=True)
        self.assertEqual([a["outcome"] for a in plan["attempts"]], ["planned"])
        self.assertEqual(plan["repaired"], [])

    def test_failed_step_stops_the_playbook(self):
        report, calls = self._run(True, api=lambda a, j: {"success": False, "error": "paused job gone"})
        self.assertEqual(len(report["failed"]), 1)
        self.assertEqual(self.fake_ledger.rows[0][0], "failed")

    def test_escalate_step_marks_escalated(self):
        with patch.object(repair, "sources") as s, patch.object(repair, "ledger", _FakeLedger()), \
                patch.object(repair, "_cron_api", lambda a, j: {"success": True}), \
                patch.object(repair, "playbooks") as pb:
            s.snapshot.return_value = _jobs()
            pb.all_playbooks.return_value = [{
                "id": "u", "source": "user", "match": {}, "steps": [{"verb": "escalate"}],
                "max_attempts_per_day": 2, "escalate_on_fail": True,
            }]
            pb.match_playbook.side_effect = lambda inc, books, job_name="": books[0]
            report = repair.cycle(data_dir=None)
            s.mark_alerted.assert_called_once()
        self.assertEqual(len(report["escalated"]), 1)
        self.assertIn("handed to the operator", report["escalated"][0]["detail"])


class AckTests(unittest.TestCase):
    def test_ack_closes_through_core(self):
        fake = SimpleNamespace(ack_incident=lambda incident_id: True)
        with patch.dict(sys.modules, {"cron": SimpleNamespace(incidents=fake), "cron.incidents": fake}):
            self.assertTrue(sources.ack("inc-1"))

    def test_ack_that_core_refuses_is_false(self):
        fake = SimpleNamespace(ack_incident=lambda incident_id: False)
        with patch.dict(sys.modules, {"cron": SimpleNamespace(incidents=fake), "cron.incidents": fake}):
            self.assertFalse(sources.ack("inc-1"))

    def test_incidents_carry_their_job_name(self):
        jobs = [{"job_id": "job-1", "name": "nightly-digest", "last_status": "error", "last_run_at": "x"}]
        incs = [{"id": "inc-1", "job_id": "job-1", "state": "detected", "failure_type": "timeout"}]
        with patch.object(sources, "_jobs", return_value=jobs), patch.object(sources, "_incidents", return_value=incs):
            snap = sources.snapshot()
        self.assertEqual(snap["incidents"][0]["job_name"], "nightly-digest")


class BudgetHandoffTests(unittest.TestCase):
    def test_budget_skip_is_a_handoff_not_silence(self):
        with patch.object(repair, "sources") as s, patch.object(repair, "ledger") as lg, \
                patch.object(repair, "playbooks") as pb:
            s.snapshot.return_value = _jobs()
            pb.all_playbooks.return_value = [{
                "id": "u", "source": "user", "match": {}, "steps": [{"verb": "rerun_job"}],
                "max_attempts_per_day": 2, "escalate_on_fail": True,
            }]
            pb.match_playbook.side_effect = lambda inc, books, job_name="": books[0]
            lg.attempts_today.return_value = 2  # today's attempts already spent
            report = repair.cycle(data_dir=None)
            s.mark_alerted.assert_called_once()
        self.assertEqual(len(report["skipped"]), 1)
        self.assertIn("daily limit", report["skipped"][0]["reason"])
        self.assertEqual(report["attempts"], [])


class HandoffTests(unittest.TestCase):
    def test_escalation_marks_the_core_incident_alerted(self):
        fake = SimpleNamespace(set_incident_state=lambda incident_id, state: True)
        with patch.dict(sys.modules, {"cron": SimpleNamespace(incidents=fake), "cron.incidents": fake}):
            self.assertTrue(sources.mark_alerted("inc-1"))

    def test_missing_core_is_reported_not_claimed(self):
        fake = SimpleNamespace(set_incident_state=lambda *a: (_ for _ in ()).throw(RuntimeError("moved")))
        with patch.dict(sys.modules, {"cron": SimpleNamespace(incidents=fake), "cron.incidents": fake}):
            self.assertFalse(sources.mark_alerted("inc-1"))

    def test_needs_you_counts_alerted_incidents(self):
        rows = [
            {"id": "a", "job_id": "j", "state": "detected", "failure_type": "script"},
            {"id": "b", "job_id": "j", "state": "alerted", "failure_type": "unknown"},
        ]
        with patch.object(sources, "_incidents", return_value=rows):
            snap = sources.snapshot()
        self.assertEqual(snap["counts"]["open_incidents"], 2)
        self.assertEqual(snap["counts"]["needs_you"], 1)


class SnapshotTests(unittest.TestCase):
    def test_upstream_failure_is_reported_not_hidden(self):
        with patch.object(sources, "_jobs", side_effect=RuntimeError("moved")), \
                patch.object(sources, "_incidents", side_effect=RuntimeError("moved")):
            snap = sources.snapshot()
        self.assertEqual(snap["health"], "unknown")
        self.assertFalse(snap["upstream"]["ok"])
        self.assertEqual(len(snap["upstream"]["errors"]), 2)

    def test_snapshot_counts_failing_jobs(self):
        with patch.object(sources, "_jobs", return_value=[{
            "job_id": "job-1", "name": "digest", "last_status": "error", "last_run_at": "x",
            "schedule": {"expr": "0 9 * * *"},
        }]), patch.object(sources, "_incidents", return_value=[]):
            snap = sources.snapshot()
        self.assertEqual(snap["counts"]["failing_jobs"], 1)
        self.assertEqual(snap["health"], "degraded")


if __name__ == "__main__":
    unittest.main()
