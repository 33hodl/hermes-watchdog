"""Route tests for the dashboard backend (the pane's API).

Regression cover for a real bug found while dogfooding: the dashboard imports
`plugin_api.py` through `spec_from_file_location`, where `from __future__ import
annotations` leaves the POST body model unresolvable and the first /repair call
raised PydanticUserError. Keep the import shape identical to the host's.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "dashboard" / "plugin_api.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_router():
    spec = importlib.util.spec_from_file_location("hermes_watchdog_api", API)
    module = importlib.util.module_from_spec(spec)
    sys.modules["hermes_watchdog_api"] = module
    spec.loader.exec_module(module)
    return module.router


class DashboardApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception:  # noqa: BLE001 - hermes venv not present in a bare checkout
            raise unittest.SkipTest("fastapi not installed")
        app = FastAPI()
        app.include_router(_load_router(), prefix="/api/plugins/hermes-watchdog")
        cls.client = TestClient(app)

    def test_status_returns_the_snapshot_shape(self):
        response = self.client.get("/api/plugins/hermes-watchdog/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in ("health", "counts", "jobs", "incidents", "upstream", "repairs"):
            self.assertIn(key, body)

    def test_repair_accepts_a_body_model(self):
        """The body model must resolve at request time (the Pydantic regression)."""
        response = self.client.post("/api/plugins/hermes-watchdog/repair", json={"dry_run": True})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["repaired"], [])

    def test_runbooks_lists_the_builtins(self):
        response = self.client.get("/api/plugins/hermes-watchdog/runbooks")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("rerun_job", body["verbs"])
        self.assertTrue(any(p["id"].startswith("builtin-") for p in body["playbooks"]))


if __name__ == "__main__":
    unittest.main()
