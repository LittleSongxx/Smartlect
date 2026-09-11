import importlib
import json
import os
import pkgutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from decimal import Decimal, localcontext
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import smartlect
from smartlect.ads.analytics import CampaignMetrics, detect_anomalies, optimize_budget_allocation, to_cents
from smartlect.config import Settings
from smartlect.recommendation.ab_test import ABTestEngine, Experiment, ExperimentGroup


class FoundationTests(unittest.TestCase):
    def test_installed_package_and_mock_entry(self):
        for module in pkgutil.walk_packages(smartlect.__path__, "smartlect."):
            importlib.import_module(module.name)
        with patch.dict(os.environ, {}, clear=True):
            result = subprocess.run([sys.executable, "-m", "smartlect.app", "--check"],
                                    capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["model_mode"], "mock")
        with patch.dict(os.environ, {"SMARTLECT_MODEL_MODE": "llm"}):
            with self.assertRaises(ValueError):
                Settings.from_env()

    def test_exact_amounts_and_absent_ratios(self):
        self.assertEqual(to_cents("90.00"), 9000)
        self.assertEqual(to_cents(Decimal("0.29")), 29)
        for invalid in (0.29, "NaN", "Infinity", "-0.01", "0.001", "invalid",
                        "100000000000000000000000000000.001"):
            with self.assertRaises(ValueError):
                to_cents(invalid)
        metric = CampaignMetrics("one", 10000)
        self.assertEqual(metric.remaining_cents, 10000)
        self.assertEqual((metric.ctr, metric.cvr, metric.cpo_cents, metric.roas), (None,) * 4)
        self.assertEqual(detect_anomalies([metric]), [])

    def test_http_health_from_outside_project(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = {**os.environ, "SMARTLECT_GROWTH_HOST": "127.0.0.1",
               "SMARTLECT_GROWTH_PORT": str(port), "SMARTLECT_MODEL_MODE": "mock",
               "SMARTLECT_GROWTH_EVENTS_ENABLED": "false", "SMARTLECT_INTERNAL_TOKEN": "fixture-internal"}
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.Popen([sys.executable, "-I", "-m", "smartlect.app"],
                                       cwd=directory, env=env, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while True:
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                            result = json.load(response)
                        break
                    except (URLError, TimeoutError):
                        if process.poll() is not None or time.monotonic() >= deadline:
                            self.fail("growth health did not become available")
                        time.sleep(0.02)
                self.assertEqual(result["service"], "smartlect-growth")
                self.assertEqual(result["phase"], "P0")
                with self.assertRaises(HTTPError) as error:
                    urlopen(f"http://127.0.0.1:{port}/recommend", timeout=0.5)
                self.assertEqual(error.exception.code, 404)
                with self.assertRaises(HTTPError) as error:
                    urlopen(f"http://127.0.0.1:{port}/internal/ledger/summary", timeout=0.5)
                self.assertEqual(error.exception.code, 401)
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(f"http://127.0.0.1:{port}/internal/ledger/summary",
                                    headers={"X-Internal-Token": "wrong-é"}), timeout=0.5)
                self.assertEqual(error.exception.code, 401)
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_budget_regression_preserves_total_and_each_cap(self):
        # B5: the source fallback produced [180, 60, 60] with a 150 item cap.
        metrics = [CampaignMetrics(str(i), 10000, spent_cents=100, paid_cents=score, stock=2)
                   for i, score in enumerate((900, 100, 100))]
        values = [a.recommended_budget_cents for a in optimize_budget_allocation(metrics, 30000)]
        self.assertEqual(sum(values), 30000)
        self.assertTrue(all(5000 <= value <= 15000 for value in values), values)
        self.assertEqual(max(values), 15000)
        # Budget is configuration, not the 100 cents spent above.
        self.assertEqual(optimize_budget_allocation(metrics)[0].current_budget_cents, 10000)

    def test_stockout_and_infeasible_budget(self):
        metrics = [CampaignMetrics("empty", 10000, spent_cents=100, paid_cents=900, stock=0)]
        allocation = optimize_budget_allocation(metrics)[0]
        self.assertEqual(allocation.recommended_budget_cents, 100)
        self.assertEqual(allocation.reason_code, "stockout_pause")
        with self.assertRaises(ValueError):
            optimize_budget_allocation(metrics, 99)
        with self.assertRaises(ValueError):
            optimize_budget_allocation(metrics * 2)
        with self.assertRaises(ValueError):
            CampaignMetrics("bad", 10, spent_cents=11)

    def test_budget_bounds_ignore_decimal_context(self):
        for precision, budget in ((2, 12348), (28, 10**28 + 5)):
            with self.subTest(precision=precision, budget=budget), localcontext() as context:
                context.prec = precision
                metrics = [CampaignMetrics("one", budget, stock=1)]
                upper = optimize_budget_allocation(metrics, budget * 2)[0].recommended_budget_cents
                lower = optimize_budget_allocation(metrics, (budget + 1) // 2)[0].recommended_budget_cents
                self.assertEqual(upper, budget * 3 // 2)
                self.assertEqual(lower, (budget + 1) // 2)

    def test_experiment_boundaries_and_config_isolation(self):
        engine = ABTestEngine(seed=42)
        for groups in ([], [ExperimentGroup("zero", weight=0)],
                       [ExperimentGroup("bad", weight=-1)]):
            with self.assertRaises(ValueError):
                engine.register_experiment(Experiment("bad", "bad", groups))
        result = engine.assign("user")
        result["config"]["rerank"] = "mutated"
        self.assertNotEqual(engine.assign("user")["config"]["rerank"], "mutated")
        engine.experiments["rec_strategy"].end_time = 1
        self.assertEqual(engine.assign("user"), {"group": "control", "config": {}})
        with self.assertRaises(ValueError):
            engine.record_metric("rec_strategy", "control", "ctr", float("nan"))


if __name__ == "__main__":
    unittest.main()
