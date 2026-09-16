"""Product review analysis: deterministic statistics from Java comments plus LLM narration.

Numbers never come from the model: star distribution, averages and the sentiment band are
computed in code from the fetched comment list; the LLM only reads those real comments and
returns structured insights (strengths / problems / keywords / suggestions). Without a live
model the snapshot still stores the deterministic statistics and marks insights unavailable.
"""
import asyncio
import json

from smartlect.events import canonical
from smartlect.privacy import redact_text
from smartlect.state import SessionStore, StateError, _actor, _public, _text

ANALYSIS_VERSION = "review-analysis-v1"
GOOD_STAR, MID_STAR = 4, 3
POSITIVE_AVG, POSITIVE_RATE = 4.5, 0.8
NEGATIVE_AVG = 3.0

INSIGHT_SYSTEM = (
    "你是电商评价分析助手。只依据给出的真实用户评价输出 JSON（不要 markdown）："
    '{"strengths": [字符串, 最多4条], "problems": [字符串, 最多4条], '
    '"keywords": [字符串, 最多8个], "suggestions": [字符串, 最多4条]}。'
    "每条都引用评价中的具体事实；评价里没有的方面不要写；不编造数字。"
)


def comment_statistics(comments):
    stars = [int(item["star"]) for item in comments if isinstance(item.get("star"), int)]
    if not stars:
        raise StateError("no_scored_comments", 422)
    good = sum(1 for star in stars if star >= GOOD_STAR)
    mid = sum(1 for star in stars if star == MID_STAR)
    bad = sum(1 for star in stars if star < MID_STAR)
    average = round(sum(stars) / len(stars), 2)
    rate = round(good / len(stars), 4)
    if average >= POSITIVE_AVG and rate >= POSITIVE_RATE:
        sentiment = "POSITIVE"
    elif average < NEGATIVE_AVG or rate < 0.5:
        sentiment = "NEGATIVE"
    else:
        sentiment = "NEUTRAL"
    return {"total": len(stars), "good": good, "mid": mid, "bad": bad, "average": average,
            "positive_rate": rate, "sentiment": sentiment}


def _validated_insights(text):
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise StateError("invalid_insights_json", 422) from None
    if not isinstance(data, dict) or set(data) != {"strengths", "problems", "keywords", "suggestions"}:
        raise StateError("invalid_insights_structure", 422)
    for key, value in data.items():
        if not isinstance(value, list) or not value or len(value) > 8 or any(
                not isinstance(item, str) or not item.strip() or len(item) > 500 for item in value):
            raise StateError("invalid_insights_structure", 422)
    return data


class ReviewAnalysisStore(SessionStore):
    def save(self, actor, product_id, stats, insights, comment_count, model_label):
        _actor(actor)
        product_id = _text(product_id, "product_id", 64)
        with self._transaction() as cursor:
            cursor.execute("""INSERT INTO review_analysis_snapshot
                (execution_scope_id,product_id,stats_json,insights_json,comment_count,analysis_version,
                 model_label,updated_by,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE stats_json=VALUES(stats_json),insights_json=VALUES(insights_json),
                comment_count=VALUES(comment_count),model_label=VALUES(model_label),
                updated_by=VALUES(updated_by),updated_at=UTC_TIMESTAMP(6)""",
                (actor.execution_scope_id, product_id, canonical(stats),
                 canonical(insights) if insights else None, comment_count, ANALYSIS_VERSION,
                 model_label, actor.actor_id))
        return self.get(actor, product_id)

    def get(self, actor, product_id):
        _actor(actor)
        with self._transaction() as cursor:
            cursor.execute("SELECT * FROM review_analysis_snapshot WHERE execution_scope_id=%s AND product_id=%s",
                (actor.execution_scope_id, _text(product_id, "product_id", 64)))
            row = cursor.fetchone()
            return _public(row) if row else None

    def list_(self, actor):
        _actor(actor)
        with self._transaction() as cursor:
            cursor.execute("""SELECT execution_scope_id,product_id,stats_json,comment_count,
                analysis_version,model_label,updated_by,updated_at FROM review_analysis_snapshot
                WHERE execution_scope_id=%s ORDER BY updated_at DESC LIMIT 100""", (actor.execution_scope_id,))
            return [_public(row) for row in cursor.fetchall()]


async def analyze(actor, commerce, provider, *, product_id, settings, store_connect):
    comments = await commerce.request("order", "/internal/order/commerce/productComments",
                                      actor=actor, data={"productId": product_id, "limit": 200})
    if not isinstance(comments, list) or not comments:
        raise StateError("no_comments", 422)
    stats = comment_statistics(comments)

    insights, model_label, insight_error = None, None, None
    if settings.model_mode == "live" and provider is not None:
        try:
            excerpt = canonical([{"star": item.get("star"), "content": redact_text(str(item.get("commentContent") or ""))[:400]}
                                 for item in comments[:80]])
            response = await provider.chat(
                [{"role": "system", "content": INSIGHT_SYSTEM},
                 {"role": "user", "content": f"商品评价如下（共 {len(comments)} 条，节选）：\n{excerpt}"}],
                response_format={"type": "json_object"}, max_tokens=1200, max_attempts=1,
                prompt_version=ANALYSIS_VERSION, schema_version="review-insights-v1")
            insights = _validated_insights(response["message"]["content"])
            model_label = f"{provider.effective_chat_model()}@live"
        except StateError:
            raise
        except Exception as error:  # insights are an enhancement, never a blocker
            insight_error = getattr(error, "code", type(error).__name__)
    else:
        insight_error = "model_not_live"

    row = await asyncio.to_thread(ReviewAnalysisStore(store_connect).save, actor, product_id, stats,
                                  insights, stats["total"], model_label)
    row["insight_error"] = insight_error
    return row
