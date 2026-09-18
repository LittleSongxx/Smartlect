"""Admin ops surface: pure mapping and catalog contracts (no database)."""
import unittest

from smartlect.adminapi.store import _agent_kind, _usage
from smartlect.adminapi.tools import DEBUG_TOOLS, catalog
from smartlect.tools import REGISTRY


class AdminApiMappingTests(unittest.TestCase):
    def test_agent_kind_discriminates_runs(self):
        self.assertEqual(_agent_kind({"is_merchant": 1}), "merchant")
        self.assertEqual(_agent_kind({"message_id": "debug:abc"}), "debug")
        self.assertEqual(_agent_kind({"message_id": "mcp:abc"}), "mcp")
        self.assertEqual(_agent_kind({"message_id": "u-1"}), "shopping")
        self.assertEqual(_agent_kind({"message_id": "mcp:abc", "is_merchant": 1}), "merchant")

    def test_usage_sums_attempts_and_tolerates_missing_fields(self):
        context = {"model_attempts": [
            {"usage": {"input_tokens": 10, "output_tokens": 5}, "cost_estimate_cny": 0.01},
            {"usage": {"input_tokens": 3}, "cost_estimate_cny": None},
            None,
        ]}
        totals = _usage(context)
        self.assertEqual(totals["input_tokens"], 13)
        self.assertEqual(totals["output_tokens"], 5)
        self.assertEqual(totals["model_attempts"], 3)
        self.assertAlmostEqual(totals["cost_estimate_cny"], 0.01)
        self.assertEqual(_usage({})["model_attempts"], 0)
        self.assertEqual(_usage(None)["model_attempts"], 0)

    def test_debug_tools_are_read_only_registry_entries(self):
        for name in DEBUG_TOOLS:
            self.assertIn(name, REGISTRY)
            self.assertEqual(REGISTRY[name].kind, "read")

    def test_catalog_lists_registry_plus_debug_probe_and_marks_debuggability(self):
        result = catalog()
        names = {item["name"] for item in result["tools"]}
        self.assertIn("catalog_search", names)
        self.assertIn("search_knowledge", names)
        self.assertNotIn("propose_order", [item["name"] for item in result["tools"] if item["debuggable"]])
        probe = next(item for item in result["tools"] if item["name"] == "catalog_search")
        self.assertTrue(probe["debug_only"])
        self.assertIn("inputSchema", probe)
        # Write/proposal/handoff tools must never be flagged debuggable.
        for item in result["tools"]:
            if REGISTRY.get(item["name"]) is not None:
                self.assertEqual(item["debuggable"], item["name"] in DEBUG_TOOLS)


if __name__ == "__main__":
    unittest.main()
