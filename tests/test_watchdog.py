"""Unit tests for the watchdog engine (stdlib unittest — no pytest needed).

Run from the plugin root:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
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

        def _api(action, job_id, **kw):
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

    def test_repaired_detail_carries_the_proof_sentence(self):
        """The pane line is the product: a verdict plus what Hermes recorded."""
        with patch.object(repair, "sources") as s, patch.object(repair, "ledger", self.fake_ledger), \
                patch.object(repair, "_cron_api", lambda a, j, **kw: {"success": True}), \
                patch.object(repair, "_verified", lambda *a: True), \
                patch.object(repair, "_evidence", lambda *a: "the next run succeeded at 09:41"):
            s.snapshot.return_value = _jobs()
            report = repair.cycle(data_dir=None)
        detail = report["repaired"][0]["detail"]
        self.assertEqual(detail, "the next run succeeded at 09:41 — Hermes's own run record")
        self.assertEqual(self.fake_ledger.rows[0][1], detail)

    def test_evidence_names_the_record_and_the_time(self):
        with patch.object(repair, "sources") as s:
            s._incidents.return_value = [{
                "id": "inc-1", "state": "resolved", "resolved_at": "2026-11-05T01:12:00Z",
            }]
            sentence = repair._evidence("job-1", "inc-1", 0.0)
        self.assertRegex(sentence, r"^core marked it resolved at \d\d:\d\d$")

    def test_evidence_is_empty_when_nothing_confirms(self):
        with patch.object(repair, "sources") as s:
            s._incidents.return_value = [{"id": "inc-1", "state": "detected"}]
            s._latest_execution.return_value = {"status": "error"}
            self.assertEqual(repair._evidence("job-1", "inc-1", 0.0), "")

    def test_a_rerun_actually_runs_before_it_is_verified(self):
        """Queueing a rerun and then verifying proves nothing; the run must finish."""
        seen = []

        def _api(action, job_id, **kw):
            seen.append((action, kw))
            return {"success": True, "job": {"executed": True, "execution_success": True}}

        with patch.object(repair, "sources") as s, patch.object(repair, "ledger", self.fake_ledger), \
                patch.object(repair, "_cron_api", _api), \
                patch.object(repair, "_verified", lambda *a: True):
            s.snapshot.return_value = _jobs()
            report = repair.cycle(data_dir=None)
        self.assertTrue(seen[0][1].get("synchronous"), "the rerun must run inside the cycle")
        self.assertEqual(report["attempts"][0]["steps"][0]["detail"], "reran the job: succeeded")

    def test_a_resolution_older_than_the_attempt_is_not_a_repair(self):
        """The job may have recovered on its own; an old resolution proves nothing."""
        with patch.object(repair, "sources") as s:
            s._incidents.return_value = [{
                "id": "inc-1", "state": "resolved", "resolved_at": "2026-11-05T00:01:00Z",
            }]
            s._latest_execution.return_value = None
            self.assertFalse(repair._verified("job-1", "inc-1", time.time()))
            self.assertEqual(repair._evidence("job-1", "inc-1", time.time()), "")

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
        self.assertIn("handed_over", report["skipped"][0])

    def test_dry_run_touches_nothing(self):
        report, calls = self._run(True)
        dry, calls_dry = self._run(True)
        self.assertEqual(calls_dry, [("run", "job-1")])

        with patch.object(repair, "sources") as s, patch.object(repair, "ledger", _FakeLedger()), \
                patch.object(repair, "_cron_api", lambda a, j, **kw: (_ for _ in ()).throw(AssertionError("ran"))):
            s.snapshot.return_value = _jobs()
            plan = repair.cycle(data_dir=None, dry_run=True)
        self.assertEqual([a["outcome"] for a in plan["attempts"]], ["planned"])
        self.assertEqual(plan["repaired"], [])

    def test_failed_step_stops_the_playbook(self):
        report, calls = self._run(True, api=lambda a, j, **kw: {"success": False, "error": "paused job gone"})
        self.assertEqual(len(report["failed"]), 1)
        self.assertEqual(self.fake_ledger.rows[0][0], "failed")

    def test_escalate_step_marks_escalated(self):
        with patch.object(repair, "sources") as s, patch.object(repair, "ledger", _FakeLedger()), \
                patch.object(repair, "_cron_api", lambda a, j, **kw: {"success": True}), \
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


class IncidentExplanationTests(unittest.TestCase):
    """An incident row must say what failed, what was tried, why it stopped and what to do."""

    def _inc(self, **kw):
        base = {"incident_id": "i1", "job_id": "job-123", "job_name": "Nightly pricing sync",
                "failure_type": "timeout", "error": "", "last_seen_at": "2026-11-12T12:00:00+00:00",
                "output_file": "/home/hermes/.hermes/cron/output/job-123.log"}
        base.update(kw)
        return base

    def test_no_error_text_still_explains_and_gives_commands(self):
        d = sources.explain_incident(self._inc(), {"job_id": "job-123", "name": "Nightly pricing sync"})
        self.assertIn("Nightly pricing sync failed", d["what"])
        self.assertIn("no error text", d["what"])
        commands = [s["command"] for s in d["steps"]]
        self.assertIn("hermes cron show job-123", commands)
        self.assertIn("hermes cron run job-123", commands)
        self.assertTrue(any("tail -n 40" in c for c in commands))

    def test_deleted_job_says_so_and_offers_no_rerun(self):
        d = sources.explain_incident(self._inc(), None)
        self.assertIn("deleted", d["why"])
        self.assertFalse(d["job_exists"])
        self.assertFalse([s for s in d["steps"] if "cron run" in s["command"]])

    def test_failed_attempt_explains_why_it_stopped(self):
        d = sources.explain_incident(
            self._inc(), {"job_id": "job-123"},
            last_attempt={"playbook": "builtin-rerun-timeout", "outcome": "failed",
                          "detail": "rerun_job", "started_at": "2026-11-12T13:00:00+00:00"},
            attempts_today=2)
        self.assertTrue(any("ran the job again" in t for t in d["tried"]))
        self.assertIn("did not hold", d["why"])
        self.assertIn("2 attempts today", " ".join(d["tried"]))

    def test_watchdogs_own_sweep_says_it_is_not_your_job(self):
        d = sources.explain_incident(self._inc(job_name="Silent repair sweep (cron incidents)",
                                               job_id="ee15", error="GatewayUnavailableError"),
                                     {"job_id": "ee15"})
        self.assertIn("Watchdog's own check", d["why"])
        self.assertTrue(any("nothing of yours" in s["text"].lower() for s in d["steps"]))

    def test_error_text_is_shown_when_hermes_recorded_it(self):
        d = sources.explain_incident(self._inc(error="ModuleNotFoundError: pandas"), {"job_id": "job-123"})
        self.assertIn("ModuleNotFoundError", d["what"])


class ToolPlaybookSafetyTests(unittest.TestCase):
    def test_check_steps_are_refused_from_the_tool(self):
        err = playbooks.tool_playbook_error({
            "id": "ok-id", "steps": [{"verb": "check", "argv": ["rm", "-rf", "/"]}]})
        self.assertIsNotNone(err)
        self.assertIn("only accepted from a playbook file", err)

    def test_safe_playbooks_are_accepted(self):
        self.assertIsNone(playbooks.tool_playbook_error({
            "id": "retry-digest", "steps": [{"verb": "rerun_job"}]}))

    def test_ids_are_strict(self):
        for bad in ("../evil", "a/b", "a\\b", "", "x" * 65, "with space"):
            self.assertIsNotNone(playbooks.tool_playbook_error({"id": bad, "steps": []}), bad)

    def test_check_runs_with_a_minimal_environment(self):
        seen = {}

        class FakeProc:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def fake_run(argv, **kwargs):
            seen.update(kwargs)
            return FakeProc()

        with patch.object(repair.subprocess, "run", fake_run), \
                patch.dict(repair.os.environ, {"OPENAI_API_KEY": "sk-secret", "PATH": "/bin"}, clear=True):
            result = repair._run_step({"verb": "check", "argv": ["true"]}, "job-1")
        self.assertTrue(result["ok"])
        self.assertEqual(seen["env"].get("PATH"), "/bin")
        self.assertNotIn("OPENAI_API_KEY", seen["env"])


class CycleStampTests(unittest.TestCase):
    def test_a_cycle_stamps_when_it_looked(self):
        import json as _json
        import tempfile
        d = Path(tempfile.mkdtemp())
        with patch.object(repair, "sources") as s, patch.object(repair, "ledger") as lg:
            s.snapshot.return_value = {"health": "ok", "upstream": {"ok": True, "errors": []},
                                       "counts": {"jobs": 1, "open_incidents": 0},
                                       "jobs": [], "incidents": []}
            repair.cycle(data_dir=d)
        stamp = repair.last_cycle(d)
        self.assertIsNotNone(stamp)
        self.assertFalse(stamp["dry_run"])
        self.assertLess(abs(stamp["checked_at"] - time.time()), 5)

    def test_no_stamp_without_a_data_dir(self):
        self.assertIsNone(repair.last_cycle(None))


class LedgerWithoutHostStorageTests(unittest.TestCase):
    """A bare checkout has no `plugins.plugin_storage`; the ledger must still work.

    This is the CI shape, and it is why a review round shipped a red badge: the
    dashboard route calls the ledger, the ledger imported core storage unguarded, so
    `/status` returned 500 in CI while passing on any machine that has core.
    """

    def test_summary_and_recent_survive_a_missing_core_storage(self):
        from hermes_watchdog import ledger

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"HERMES_HOME": tmp}):
                with patch.dict(sys.modules, {"plugins.plugin_storage": None}):
                    self.assertEqual(ledger.summary()["repaired_7d"], 0)
                    self.assertEqual(ledger.recent(limit=5), [])
                    self.assertTrue((Path(tmp) / "plugin-data" / "hermes-watchdog" / "ledger.db").exists())


class LedgerRowShapeTests(unittest.TestCase):
    def test_last_attempt_accepts_plain_tuple_rows(self):
        class FakeConn:
            def execute(self, *a, **k):
                return self

            def fetchone(self):
                return ("inc-1", "job-1", "digest", "builtin-rerun-timeout", 1000.0, "escalated", "detail")

        from hermes_watchdog import ledger as real_ledger
        with patch.object(real_ledger, "_conn", lambda: FakeConn()):
            row = real_ledger.last_attempt("inc-1")
        self.assertEqual(row["incident_id"], "inc-1")
        self.assertEqual(row["outcome"], "escalated")


class AutoCloseTests(unittest.TestCase):
    def _snapshot(self):
        return {
            "health": "degraded", "upstream": {"ok": True, "errors": []},
            "counts": {"jobs": 1, "open_incidents": 1},
            "jobs": [{"job_id": "job-1", "name": "digest"}],
            "incidents": [{"incident_id": "inc-1", "job_id": "job-1", "state": "alerted",
                           "failure_type": "unknown", "error": "interrupted"}],
        }

    def test_a_day_old_handoff_closes_itself(self):
        with patch.object(repair, "sources") as s, patch.object(repair, "ledger") as lg:
            s.snapshot.return_value = self._snapshot()
            s.job_exists.return_value = True
            s.ack.return_value = (True, "closed")
            lg.last_attempt.return_value = {"outcome": "escalated", "started_at": time.time() - 90000}
            report = repair.cycle(data_dir=None)
            s.ack.assert_called_once_with("inc-1")
        self.assertEqual(len(report["stale"]), 1)
        self.assertTrue(report["stale"][0]["closed"])

    def test_a_fresh_handoff_is_left_alone(self):
        with patch.object(repair, "sources") as s, patch.object(repair, "ledger") as lg:
            s.snapshot.return_value = self._snapshot()
            s.job_exists.return_value = True
            lg.last_attempt.return_value = {"outcome": "escalated", "started_at": time.time() - 600}
            report = repair.cycle(data_dir=None)
            s.ack.assert_not_called()
        self.assertEqual(report["stale"], [])
        self.assertEqual(len(report["skipped"]), 1)


class AlreadyHandedOverTests(unittest.TestCase):
    def test_alerted_incident_is_not_escalated_twice(self):
        with patch.object(repair, "sources") as s, patch.object(repair, "ledger") as lg, \
                patch.object(repair, "playbooks") as pb:
            s.snapshot.return_value = {
                "health": "degraded", "upstream": {"ok": True, "errors": []},
                "counts": {"jobs": 1, "open_incidents": 1},
                "jobs": [{"job_id": "job-1", "name": "digest"}],
                "incidents": [{"incident_id": "inc-1", "job_id": "job-1",
                               "state": "alerted", "failure_type": "unknown", "error": "interrupted"}],
            }
            s.job_exists.return_value = True
            report = repair.cycle(data_dir=None)
            pb.match_playbook.assert_not_called()
            lg.start_attempt.assert_not_called()
        self.assertEqual(len(report["skipped"]), 1)
        self.assertIn("already handed", report["skipped"][0]["reason"])


class OrphanedIncidentTests(unittest.TestCase):
    def test_incident_for_a_deleted_job_is_closed_not_repaired(self):
        with patch.object(repair, "sources") as s, patch.object(repair, "ledger") as lg, \
                patch.object(repair, "playbooks") as pb:
            s.snapshot.return_value = _jobs()
            s.job_exists.return_value = False
            s.ack.return_value = (True, "closed")
            report = repair.cycle(data_dir=None)
            pb.match_playbook.assert_not_called()
            lg.start_attempt.assert_not_called()
        self.assertEqual(len(report["stale"]), 1)
        self.assertTrue(report["stale"][0]["closed"])

    def test_unknown_job_state_does_not_close_anything(self):
        with patch.object(repair, "sources") as s, patch.object(repair, "ledger", _FakeLedger()), \
                patch.object(repair, "playbooks") as pb, \
                patch.object(repair, "_cron_api", lambda a, j, **kw: {"success": True}):
            s.snapshot.return_value = _jobs()
            s.job_exists.return_value = None
            pb.all_playbooks.return_value = [{
                "id": "u", "source": "user", "match": {}, "steps": [{"verb": "rerun_job"}],
                "max_attempts_per_day": 2, "escalate_on_fail": True,
            }]
            pb.match_playbook.side_effect = lambda inc, books, job_name="": books[0]
            report = repair.cycle(data_dir=None)
            s.ack.assert_not_called()
        self.assertEqual(report["stale"], [])


class AckTests(unittest.TestCase):
    def test_ack_closes_through_core(self):
        fake = SimpleNamespace(list_incidents=lambda: [{"id": "inc-1"}], ack_incident=lambda incident_id: True)
        with patch.dict(sys.modules, {"cron": SimpleNamespace(incidents=fake), "cron.incidents": fake}):
            self.assertTrue(sources.ack("inc-1")[0])

    def test_ack_that_core_refuses_is_false(self):
        fake = SimpleNamespace(list_incidents=lambda: [{"id": "inc-1"}], ack_incident=lambda incident_id: False)
        with patch.dict(sys.modules, {"cron": SimpleNamespace(incidents=fake), "cron.incidents": fake}):
            self.assertFalse(sources.ack("inc-1")[0])

    def test_ack_reports_a_mismatched_id_instead_of_guessing(self):
        fake = SimpleNamespace(list_incidents=lambda: [{"id": "real-id"}], ack_incident=lambda i: True)
        with patch.dict(sys.modules, {"cron": SimpleNamespace(incidents=fake), "cron.incidents": fake}):
            closed, reason = sources.ack("stale-id")
        self.assertFalse(closed)
        self.assertIn("not in the cron store", reason)

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
        self.assertIn("handed_over", report["skipped"][0])
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


class DemoTests(unittest.TestCase):
    """The demo is the only place a repair happens on purpose — it must be real and tidy."""

    def _run(self, outcome="repaired", detail="the next run succeeded at 09:41"):
        from hermes_watchdog import demo

        calls = []

        def _api(action, **kw):
            calls.append((action, kw))
            if action == "create":
                return {"success": True, "job": {"job_id": "job-demo"}}
            return {"success": True}

        cycle_report = {
            "attempts": [{"outcome": outcome, "detail": detail,
                          "steps": [{"verb": "rerun_job", "ok": True, "detail": "reran the job: succeeded"}]}],
            "repaired": [{"outcome": outcome}] if outcome == "repaired" else [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"HERMES_HOME": tmp}), \
                    patch.object(demo, "_cron_api", _api), \
                    patch.object(demo, "_run_sync", lambda job_id: {"success": True}), \
                    patch.object(demo, "_open_incident_for", lambda job_id: "inc-demo"), \
                    patch.object(demo, "repair") as rp, patch.object(demo, "ledger") as lg:
                rp.cycle.return_value = cycle_report
                report = demo.run(data_dir=None)
            scripts = sorted(f.name for f in (Path(tmp) / "scripts").glob("*")) if (Path(tmp) / "scripts").exists() else []
        return report, calls, scripts, lg

    def test_the_demo_repairs_a_real_job_and_removes_it(self):
        report, calls, scripts, lg = self._run()
        self.assertTrue(report["ok"])
        self.assertEqual(report["outcome"], "repaired")
        self.assertEqual(report["detail"], "the next run succeeded at 09:41")
        # Created, repaired, then deleted — no demo job is left behind.
        self.assertEqual([c[0] for c in calls], ["create", "remove"])
        self.assertEqual(scripts, [])
        self.assertTrue(report["cleaned_up"])
        lg.mark_demo.assert_called_once_with("inc-demo")

    def test_the_demo_creates_the_job_silently(self):
        """A demo must not page the owner: local delivery, no agent turn."""
        _, calls, _, _ = self._run()
        created = calls[0][1]
        self.assertEqual(created["deliver"], "local")
        self.assertTrue(created["no_agent"])

    def test_the_demo_uses_the_active_profile_not_the_launch_one(self):
        """A multi-profile process must not drop the demo into the profile it launched with.

        ``HERMES_HOME`` is pinned at launch; the active profile's home comes from
        ``hermes_constants.get_hermes_home`` (context-local override first).
        """
        from types import ModuleType

        from hermes_watchdog import demo

        with tempfile.TemporaryDirectory() as launch, tempfile.TemporaryDirectory() as active:
            # A stub stands in for core, so this test runs in a bare checkout too.
            core = ModuleType("hermes_constants")
            core.get_hermes_home = lambda: Path(active)
            with patch.dict(os.environ, {"HERMES_HOME": launch}), \
                    patch.dict(sys.modules, {"hermes_constants": core}):
                self.assertEqual(demo._home(), Path(active))

    def test_the_demo_falls_back_when_core_has_no_get_hermes_home(self):
        """A host without core's helper still gets a sane path, never a crash."""
        from hermes_watchdog import demo

        with tempfile.TemporaryDirectory() as launch:
            with patch.dict(os.environ, {"HERMES_HOME": launch}), \
                    patch.dict(sys.modules, {"hermes_constants": None}):
                self.assertEqual(demo._home(), Path(launch))

    def test_a_failed_demo_says_so_and_is_not_tagged(self):
        report, calls, _, lg = self._run(outcome="failed", detail="steps ran but the failure is still open")
        self.assertFalse(report["ok"])
        self.assertEqual(report["outcome"], "failed")
        lg.mark_demo.assert_not_called()
        self.assertEqual(calls[-1][0], "remove")


class DemoCountsTests(unittest.TestCase):
    def test_demo_rows_do_not_flatter_the_fleet(self):
        from hermes_watchdog import ledger

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"HERMES_HOME": tmp}), \
                    patch.dict(sys.modules, {"plugins.plugin_storage": None}):
                real = ledger.start_attempt("inc-1", "job-1", "digest", "builtin-rerun-timeout", "builtin")
                ledger.finish_attempt(real, "repaired", "core marked it resolved at 09:41")
                mock = ledger.start_attempt("inc-2", "job-demo", "demo job", "builtin-rerun-timeout", "builtin")
                ledger.finish_attempt(mock, "repaired", "core marked it resolved at 09:42")
                ledger.mark_demo("inc-2")
                summary = ledger.summary()
                recent = ledger.recent(limit=5)
        self.assertEqual(summary["repaired_7d"], 1)
        self.assertEqual([r["demo"] for r in recent], [True, False])


if __name__ == "__main__":
    unittest.main()
