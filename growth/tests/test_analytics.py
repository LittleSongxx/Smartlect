"""Review statistics and growth snapshot determinism; LLM narration is optional."""
import asyncio
import json
import unittest
import uuid
from unittest.mock import MagicMock, Mock

import httpx

from smartlect.auth import ActorContext
from smartlect.config import Settings
from smartlect.growth_report import _validated_suggestions, build_snapshot
from smartlect.review_analysis import _validated_insights, comment_statistics
from smartlect.state import StateError

ACTOR = ActorContext(subject_type="merchant", actor_id="boss", session_id="s",
                     permissions=("admin:legacy",), execution_scope_id="scope")


def comments(stars):
    return [{"star": star, "commentContent": f"评语{index}"} for index, star in enumerate(stars)]


class StatisticsTests(unittest.TestCase):
    def test_deterministic_bands_and_rates(self):
        stats = comment_statistics(comments([5, 4, 4, 5, 3, 2, 1, 4]))
        self.assertEqual(stats["total"], 8)
        self.assertEqual((stats["good"], stats["mid"], stats["bad"]), (5, 1, 2))
        self.assertEqual(stats["sentiment"], "NEUTRAL")
        self.assertEqual(comment_statistics(comments([5, 5, 5, 5]))["sentiment"], "POSITIVE")
        self.assertEqual(comment_statistics(comments([1, 1, 2, 5]))["sentiment"], "NEGATIVE")
        with self.assertRaises(StateError):
            comment_statistics([{"star": None, "commentContent": "无星级"}])

    def test_insight_and_suggestion_schema_gates(self):
        good = {"strengths": ["保温好"], "problems": ["杯盖漏"], "keywords": ["保温"], "suggestions": ["加强质检"]}
        self.assertEqual(_validated_insights(json.dumps(good)), good)
        for broken in ('{"strengths": []}', "not json", '{"strengths": 1, "problems": [], "keywords": [], "suggestions": []}'):
            with self.assertRaises(StateError):
                _validated_insights(broken)

        self.assertEqual(_validated_suggestions('{"suggestions": ["a", "b", "c"]}'), ["a", "b", "c"])
        with self.assertRaises(StateError):
            _validated_suggestions('{"suggestions": ["a"]}')  # fewer than 3

    def test_snapshot_numbers_come_from_stores_not_models(self):
        # The shape must be AttributionStore.totals(), the call the endpoint actually makes;
        # a hand-made flat dict would keep passing while the page rendered nothing.
        totals = {"paid_cents": 1000, "refunded_cents": 200, "net_cents": 800, "payment_conversions": 3}
        snapshot = build_snapshot(totals, {"conversations": 9})
        self.assertEqual(snapshot["payments"], {"paid_cents": 1000, "refunded_cents": 200,
                                                "net_cents": 800, "conversions": 3})
        self.assertEqual(snapshot["ai_activity"]["conversations"], 9)

    def test_analyze_stores_stats_even_without_live_model(self):
        from smartlect.review_analysis import ReviewAnalysisStore, analyze

        def java(request):
            if request.url.path == "/internal/identity/introspect":
                return httpx.Response(200, json={"status": "success", "data": {
                    "subjectType": "merchant", "actorId": "boss", "sessionId": "s",
                    "permissions": ["admin:legacy"]}})
            if request.url.path == "/internal/order/commerce/productComments":
                return httpx.Response(200, json={"status": "success", "data": comments([5, 4, 5])})
            raise AssertionError(request.url.path)

        from smartlect.commerce import AsyncCommerceClient
        commerce = AsyncCommerceClient({"SMARTLECT_ORDER_PORT": "18104", "SMARTLECT_INTERNAL_TOKEN": "t"},
                                       transport=httpx.MockTransport(java))
        connection, cursor = MagicMock(), MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.rowcount = 1
        cursor.fetchone.return_value = {"execution_scope_id": "scope", "product_id": "p1",
            "stats": {"total": 3, "good": 3, "mid": 0, "bad": 0, "average": 4.67, "positive_rate": 1.0, "sentiment": "POSITIVE"},
            "insights": None, "comment_count": 3, "analysis_version": "review-analysis-v1",
            "model_label": None, "updated_by": "boss", "updated_at": "2026-09-16T00:00:00Z"}
        connect = Mock(return_value=connection)
        row = asyncio.run(analyze(ACTOR, commerce, provider=None, product_id="p1",
                                  settings=Settings(model_mode="mock"), store_connect=connect))
        self.assertEqual(row["stats"]["total"], 3)
        self.assertEqual(row["insights"], None)
        self.assertEqual(row["insight_error"], "model_not_live")


if __name__ == "__main__":
    unittest.main()
