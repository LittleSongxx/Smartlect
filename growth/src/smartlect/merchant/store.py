"""Committed observations and plans; reuse the existing fenced AgentRun runtime."""

from datetime import timedelta
from hashlib import sha256
import json
import uuid

from pydantic import ValidationError

from smartlect.ads.analytics import LOW_CTR_PER_MILLE
from smartlect.ads.service import AdAction
from smartlect.ads.store import AdsStore, _fields, _merchant, _money, policy_range
from smartlect.attribution import iso
from smartlect.events import canonical
from smartlect.privacy import redact_text
from smartlect.recommendation.store import strategy_config
from smartlect.state import StateError, _integer, _public, _text


def action_priority(action):
    kind = action["action_type"]
    if kind.startswith("pause_"):
        return 0
    return {
        "set_budget": 1,
        "replace_creative": 2,
        "activate_campaign": 3,
        "resume_campaign": 3,
        "activate_creative": 4,
        "resume_creative": 4,
        "set_recommendation_policy": 5,
    }[kind]


def plan_batches(plan):
    batches = []
    for action in sorted(plan["spec"]["actions"], key=action_priority):
        if (
            action["action_type"] == "set_budget"
            and batches
            and batches[-1][0]["action_type"] == "set_budget"
        ):
            batches[-1].append(action)
        else:
            batches.append([action])
    return batches


def plan_action_request(plan, index, batch):
    identifier = sha256(
        f"merchant:{plan['plan_id']}:{plan['version']}:{index}".encode()
    ).hexdigest()[:32]
    authorization = plan.get("authorization") or {}
    transitions = (
        authorization.get("approval_resource_transitions", [])
        if authorization.get("grant_id") == plan["grant_id"]
        else []
    )
    deltas = {
        (t["kind"], t["resource_id"]): t["after"]["version"] - t["before"]["version"]
        for t in transitions
    }
    actions = []
    for action in batch:
        resource = (
            "creative" if action["action_type"].endswith("_creative") else "campaign"
        )
        delta = deltas.get((resource, action.get(resource + "_id")), 0)
        actions.append(
            {**action, "expected_version": action["expected_version"] + delta}
            if delta
            else action
        )
    return {
        "action_id": identifier,
        "idempotency_key": "merchant:" + identifier,
        "grant_id": plan["grant_id"],
        "plan_id": plan["plan_id"],
        "plan_version": plan["version"],
        "agent_run_id": plan["agent_run_id"],
        "round_id": plan["spec"]["round_id"],
        "reason_code": "merchant_observation_plan",
        "evidence_ids": plan["spec"]["evidence_ids"],
        "actions": actions,
    }


class MerchantStore(AdsStore):
    def grant_scope_access(self, actor_id, scope, label):
        """Local scenario registration only; never a model or public API capability."""
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO merchant_scope_access VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE label=label",
                (
                    _text(actor_id, "actor_id", 64),
                    _text(scope, "scope"),
                    _text(label, "label", 200),
                ),
            )

    def scopes(self, actor):
        _merchant(actor)
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT execution_scope_id,label FROM merchant_scope_access WHERE actor_id=%s ORDER BY execution_scope_id",
                (actor.actor_id,),
            )
            return {
                "items": [
                    {"execution_scope_id": "store", "label": "默认店铺"},
                    *list(cursor.fetchall()),
                ]
            }

    def selected_actor(self, actor):
        if actor.subject_type != "merchant":
            return actor
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT s.execution_scope_id FROM merchant_scope_selection s JOIN merchant_scope_access a ON a.actor_id=s.actor_id AND a.execution_scope_id=s.execution_scope_id WHERE s.session_hash=%s AND s.actor_id=%s",
                (sha256(actor.session_id.encode()).hexdigest(), actor.actor_id),
            )
            row = cursor.fetchone()
            return actor.model_copy(
                update={
                    "execution_scope_id": row["execution_scope_id"] if row else "store"
                }
            )

    def select_scope(self, actor, scope):
        _merchant(actor)
        _text(scope, "scope")
        if scope not in {r["execution_scope_id"] for r in self.scopes(actor)["items"]}:
            raise StateError("scope_not_authorized", 403)
        with self._transaction() as cursor:
            key = sha256(actor.session_id.encode()).hexdigest()
            if scope == "store":
                cursor.execute(
                    "DELETE FROM merchant_scope_selection WHERE session_hash=%s AND actor_id=%s",
                    (key, actor.actor_id),
                )
            else:
                cursor.execute(
                    "INSERT INTO merchant_scope_selection VALUES (%s,%s,%s) AS incoming "
                    "ON DUPLICATE KEY UPDATE execution_scope_id=incoming.execution_scope_id",
                    (key, actor.actor_id, scope),
                )
        return actor.model_copy(update={"execution_scope_id": scope})

    def _latest_plan(self, cursor, actor):
        cursor.execute(
            "SELECT * FROM merchant_plan WHERE execution_scope_id=%s AND actor_id=%s ORDER BY created_at DESC,plan_id DESC LIMIT 1",
            (actor.execution_scope_id, actor.actor_id),
        )
        row = cursor.fetchone()
        return _public(row) if row else None

    def observation(self, actor):
        """Called after current Java stock reads have committed their protection."""
        _merchant(actor)
        with self._transaction() as cursor:
            self._lock(cursor, actor)
            cursor.execute(
                "SELECT * FROM ads_campaign WHERE execution_scope_id=%s AND owner_id=%s ORDER BY campaign_id LIMIT 20",
                (actor.execution_scope_id, actor.actor_id),
            )
            campaigns = [_public(r) for r in cursor.fetchall()]
            cursor.execute(
                "SELECT * FROM ads_creative WHERE execution_scope_id=%s AND owner_id=%s ORDER BY creative_id LIMIT 100",
                (actor.execution_scope_id, actor.actor_id),
            )
            creatives = [_public(r) for r in cursor.fetchall()]
            cursor.execute(
                "SELECT * FROM ads_inventory WHERE execution_scope_id=%s ORDER BY product_id,sku_key",
                (actor.execution_scope_id,),
            )
            inventory = {(r["product_id"], r["sku_key"]): r for r in cursor.fetchall()}
            cursor.execute(
                "SELECT JSON_UNQUOTE(JSON_EXTRACT(result_json,'$.campaign_id')) AS campaign_id,exposure_id,created_at FROM ad_interaction WHERE execution_scope_id=%s ORDER BY created_at,exposure_id",
                (actor.execution_scope_id,),
            )
            impressions = list(cursor.fetchall())
            cursor.execute(
                "SELECT click_id,campaign_id,amount_cents,occurred_at FROM ad_spend WHERE execution_scope_id=%s ORDER BY occurred_at,click_id",
                (actor.execution_scope_id,),
            )
            clicks = list(cursor.fetchall())
            cursor.execute(
                "SELECT touch_id,kind,occurred_at FROM traffic_touch WHERE execution_scope_id=%s AND kind IN ('REC_IMPRESSION','REC_CLICK') ORDER BY occurred_at,touch_id",
                (actor.execution_scope_id,),
            )
            recommendation_touches = list(cursor.fetchall())
            recommendation_impressions = [
                r for r in recommendation_touches if r["kind"] == "REC_IMPRESSION"
            ]
            recommendation_clicks = [
                r for r in recommendation_touches if r["kind"] == "REC_CLICK"
            ]
            cursor.execute(
                """SELECT e.event_id,e.event_type,e.pay_order_id,e.amount_cents,e.occurred_at,e.raw_json,
                a.campaign_id,a.category,a.calculation_status FROM commerce_event e
                LEFT JOIN commerce_attribution a USING(event_id)
                LEFT JOIN commerce_attribution_meta m USING(event_id)
                WHERE e.status='APPLIED' AND COALESCE(a.execution_scope_id,m.execution_scope_id,'store')=%s
                ORDER BY e.occurred_at,e.event_id""",
                (actor.execution_scope_id,),
            )
            events = list(cursor.fetchall())
            cursor.execute(
                "SELECT recommendation_id,result_json,created_at FROM recommendation_receipt WHERE execution_scope_id=%s ORDER BY created_at,recommendation_id",
                (actor.execution_scope_id,),
            )
            empty = [
                r
                for r in cursor.fetchall()
                if not json.loads(r["result_json"]).get("items")
            ]
            cursor.execute(
                "SELECT action_id,request_json,result_json FROM growth_action WHERE execution_scope_id=%s ORDER BY action_id",
                (actor.execution_scope_id,),
            )
            rejected = [
                r
                for r in cursor.fetchall()
                if json.loads(r["result_json"]).get("status") == "REJECTED"
            ]
            cursor.execute(
                "SELECT * FROM growth_diagnostic_fact WHERE execution_scope_id=%s ORDER BY occurred_at,signal_id",
                (actor.execution_scope_id,),
            )
            stock_rejections = list(cursor.fetchall())
            failures = [
                e
                for e in events
                if e["event_type"] == "PAYMENT_ATTEMPT"
                and json.loads(e["raw_json"]).get("payload", {}).get("attemptStatus")
                == "DECLINED"
            ]
            cancellations = [e for e in events if e["event_type"] == "CANCEL"]
            # Only external outcomes, including rejected actions, form this watermark.
            # A new timestamp/generation or successful budget edit is not new traffic.
            water_data = {
                "impressions": [r["exposure_id"] for r in impressions],
                "clicks": [r["click_id"] for r in clicks],
                "recommendation_impressions": [
                    r["touch_id"] for r in recommendation_impressions
                ],
                "recommendation_clicks": [r["touch_id"] for r in recommendation_clicks],
                "events": [e["event_id"] for e in events],
                "empty": [r["recommendation_id"] for r in empty],
                "stock_rejections": [r["signal_id"] for r in stock_rejections],
                "resource_ids": [c["campaign_id"] for c in campaigns]
                + [c["creative_id"] for c in creatives],
                "stocks": [
                    (
                        c["product_id"],
                        c["sku_key"],
                        inventory.get((c["product_id"], c["sku_key"]), {}).get("stock"),
                    )
                    for c in campaigns
                ],
            }
            watermark = sha256(canonical(water_data).encode()).hexdigest()
            cursor.execute(
                "SELECT * FROM merchant_observation WHERE execution_scope_id=%s AND actor_id=%s ORDER BY round_number DESC LIMIT 1",
                (actor.execution_scope_id, actor.actor_id),
            )
            previous = cursor.fetchone()
            unknown_attribution = len(
                [
                    e
                    for e in events
                    if e["event_type"] == "PAYMENT" and not e.get("campaign_id")
                ]
            )
            if previous and previous["watermark"] == watermark:
                snap = json.loads(previous["snapshot_json"])
                summary = snap.get("summary")
                if isinstance(summary, dict):
                    snap["summary"] = {
                        **summary,
                        "unknown_attribution": unknown_attribution,
                    }
                return snap
            round_number = previous["round_number"] + 1 if previous else 1
            identifier, now = uuid.uuid4().hex, self.clock()
            facts = []

            def fact(
                metric, value, kind, source_ids, occurred_at=None, campaign_id=None
            ):
                evidence_id = identifier + ":" + str(len(facts) + 1)
                record = {
                    "evidence_id": evidence_id,
                    "kind": kind,
                    "metric": metric,
                    "value": value,
                    "source": kind,
                    "source_ids": source_ids[-20:],
                    "source_total_count": len(source_ids),
                    "source_ids_truncated": len(source_ids) > 20,
                    "observed_at": iso(now),
                    "occurred_at": iso(occurred_at) if occurred_at else None,
                }
                if campaign_id:
                    record["campaign_id"] = campaign_id
                facts.append(record)
                return evidence_id

            for campaign in campaigns:
                cid = campaign["campaign_id"]
                inv = inventory.get((campaign["product_id"], campaign["sku_key"]), {})
                ims = [r for r in impressions if r["campaign_id"] == cid]
                cls = [r for r in clicks if r["campaign_id"] == cid]
                evs = [r for r in events if r["campaign_id"] == cid]
                pay = [e for e in evs if e["event_type"] == "PAYMENT"]
                refund = [e for e in evs if e["event_type"] == "REFUND"]
                values = {
                    "stock": inv.get("stock"),
                    "impressions": len(ims),
                    "clicks": len(cls),
                    "spend_cents": sum(c["amount_cents"] for c in cls),
                    "paid_cents": sum(e["amount_cents"] for e in pay),
                    "refunded_cents": sum(e["amount_cents"] for e in refund),
                    "payment_conversions": len({e["pay_order_id"] for e in pay}),
                }
                campaign["metrics"] = values
                campaign["creatives"] = [
                    c for c in creatives if c["campaign_id"] == cid
                ]
                campaign["evidence_ids"] = []
                for metric, value in values.items():
                    source = (
                        "inventory"
                        if metric == "stock"
                        else (
                            "commerce"
                            if metric
                            in {"paid_cents", "refunded_cents", "payment_conversions"}
                            else "ads"
                        )
                    )
                    source_rows = (
                        (refund if metric == "refunded_cents" else pay)
                        if source == "commerce"
                        else ims if metric == "impressions" else cls
                    )
                    id_field = (
                        "event_id"
                        if source == "commerce"
                        else "exposure_id" if metric == "impressions" else "click_id"
                    )
                    ids = [r[id_field] for r in source_rows]
                    event_time = max(
                        (
                            (
                                r["created_at"]
                                if metric == "impressions"
                                else r["occurred_at"]
                            )
                            for r in source_rows
                        ),
                        default=None,
                    )
                    if source == "inventory":
                        ids = [
                            f"{campaign['product_id']}:{campaign['sku_key']}:{inv.get('observed_generation',0)}"
                        ]
                        event_time = None  # Java Stock DTO has no authoritative business timestamp.
                    campaign["evidence_ids"].append(
                        fact(metric, value, source, ids, event_time, cid)
                    )
                    if source == "inventory":
                        facts[-1]["inventory_observation"] = _public(inv)
            summary = {
                "impressions": len(impressions),
                "clicks": len(clicks),
                "spend_cents": sum(c["amount_cents"] for c in clicks),
                "recommendation_impressions": len(recommendation_impressions),
                "recommendation_clicks": len(recommendation_clicks),
                "paid_cents": sum(
                    e["amount_cents"] for e in events if e["event_type"] == "PAYMENT"
                ),
                "refunded_cents": sum(
                    e["amount_cents"] for e in events if e["event_type"] == "REFUND"
                ),
                "payment_conversions": len(
                    {e["pay_order_id"] for e in events if e["event_type"] == "PAYMENT"}
                ),
                "payment_failures": len(failures),
                "cancelled_orders": len(cancellations),
                "empty_recommendations": len(empty),
                "stock_rejections": len(stock_rejections),
                "unknown_attribution": unknown_attribution,
            }
            for metric, touches in (
                ("recommendation_impressions", recommendation_impressions),
                ("recommendation_clicks", recommendation_clicks),
            ):
                fact(
                    metric,
                    len(touches),
                    "recommendation",
                    [r["touch_id"] for r in touches],
                    max((r["occurred_at"] for r in touches), default=None),
                )
            for metric, value, kind, ids in (
                (
                    "payment_failures",
                    len(failures),
                    "payment_attempt",
                    [e["event_id"] for e in failures],
                ),
                (
                    "cancelled_orders",
                    len(cancellations),
                    "commerce",
                    [e["event_id"] for e in cancellations],
                ),
                (
                    "empty_recommendations",
                    len(empty),
                    "recommendation",
                    [e["recommendation_id"] for e in empty],
                ),
                (
                    "stock_rejections",
                    summary["stock_rejections"],
                    "inventory",
                    [r["signal_id"] for r in stock_rejections],
                ),
            ):
                fact(
                    metric,
                    value,
                    kind,
                    ids,
                    (
                        max((e["occurred_at"] for e in failures), default=None)
                        if metric == "payment_failures"
                        else None
                    ),
                )
            result = {
                "observation_id": identifier,
                "watermark": watermark,
                "round_id": f"merchant-round-{round_number}",
                "round_number": round_number,
                "execution_scope_id": actor.execution_scope_id,
                "observed_at": iso(now),
                "period": "scope_lifetime",
                "facts": facts,
                "campaigns": campaigns,
                "summary": summary,
                "maturity": {
                    "minimum_clicks": 10,
                    "minimum_creative_impressions": 100,
                    "minimum_recommendation_clicks": 10,
                    "financial_sample_maturity": "not_established_by_click_screening",
                    "creative_low_ctr_per_mille": LOW_CTR_PER_MILLE,
                    "causal_conclusion_supported": False,
                },
                "payment_attempts": [
                    {
                        k: json.loads(e["raw_json"]).get("payload", {}).get(k)
                        for k in (
                            "attemptId",
                            "payOrderId",
                            "attemptStatus",
                            "reasonCode",
                            "paymentMode",
                            "occurredAt",
                        )
                    }
                    | {"event_id": e["event_id"], "occurred_at": iso(e["occurred_at"])}
                    for e in failures[-20:]
                ],
                "attribution_categories": sorted(
                    {e["category"] for e in events if e.get("category")}
                ),
                "financial_event_watermark": {
                    "count": len(events),
                    "last_event_id": events[-1]["event_id"] if events else None,
                },
            }
            self._insert(
                cursor,
                "merchant_observation",
                {
                    "observation_id": identifier,
                    "execution_scope_id": actor.execution_scope_id,
                    "actor_id": actor.actor_id,
                    "round_number": round_number,
                    "watermark": watermark,
                    "snapshot_json": canonical(result),
                    "observed_at": now,
                },
            )
            return result

    def merchant_snapshot(self, actor):
        _merchant(actor)
        ads = self.snapshot(actor)
        with self._transaction() as cursor:
            result = {}
            for name, table, sort in (
                ("observations", "merchant_observation", "round_number"),
                ("plans", "merchant_plan", "created_at"),
                ("memories", "merchant_experience", "created_at"),
            ):
                cursor.execute(
                    f"SELECT * FROM {table} WHERE execution_scope_id=%s AND actor_id=%s ORDER BY {sort} DESC LIMIT 30",
                    (actor.execution_scope_id, actor.actor_id),
                )
                result[name] = [
                    (
                        json.loads(r["snapshot_json"])
                        if name == "observations"
                        else _public(r)
                    )
                    for r in cursor.fetchall()
                ]
            cursor.execute(
                "SELECT r.* FROM agent_run r JOIN merchant_run_context c USING(agent_run_id) WHERE c.execution_scope_id=%s AND c.actor_id=%s ORDER BY r.created_at DESC LIMIT 30",
                (actor.execution_scope_id, actor.actor_id),
            )
            result["runs"] = [_public(r) for r in cursor.fetchall()]
        result["account"] = ads["account"]
        result["grant"] = next(
            (
                g
                for g in ads["grants"]
                if ads["account"] and g["grant_id"] == ads["account"]["grant_id"]
            ),
            None,
        )
        return result

    def request_replay(self, actor, request):
        _merchant(actor)
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT * FROM merchant_run_context WHERE execution_scope_id=%s AND actor_id=%s AND request_id=%s",
                (actor.execution_scope_id, actor.actor_id, request["request_id"]),
            )
            row = cursor.fetchone()
        if row:
            if row["request_hash"] != sha256(canonical(request).encode()).hexdigest():
                raise StateError("merchant_request_conflict", 409)
            return self.get_run(actor, row["agent_run_id"])
        return None

    def prepare_run_context(self, actor, run, observation, request):
        _merchant(actor)
        request_id = _text(request.get("request_id"), "request_id")
        objective = redact_text(_text(request.get("objective"), "objective", 1000))
        request_hash = sha256(canonical(request).encode()).hexdigest()
        with self._transaction() as cursor:
            self._lock(cursor, actor)
            owned_run = self._owned_record(cursor, actor, run["agent_run_id"], "run")
            if run.get("conversation_id") != owned_run["conversation_id"]:
                raise StateError("merchant_run_not_found", 404)
            stored_observation = self._row(
                cursor,
                actor,
                "merchant_observation",
                "observation_id",
                observation["observation_id"],
            )
            if stored_observation["actor_id"] != actor.actor_id:
                raise StateError("merchant_observation_not_found", 404)
            if canonical(observation) != canonical(
                json.loads(stored_observation["snapshot_json"])
            ):
                raise StateError("merchant_observation_mismatch", 409)
            previous = self._latest_plan(cursor, actor)
            cursor.execute(
                "SELECT * FROM merchant_run_context WHERE agent_run_id=%s",
                (run["agent_run_id"],),
            )
            linked = cursor.fetchone()
            if linked:
                if (
                    linked["actor_id"] != actor.actor_id
                    or linked["execution_scope_id"] != actor.execution_scope_id
                    or linked["observation_id"] != observation["observation_id"]
                    or linked["request_id"] != request_id
                    or linked["request_hash"] != request_hash
                ):
                    raise StateError("merchant_request_conflict", 409)
                return
            cursor.execute(
                "SELECT product_id,budget_cents FROM ads_campaign WHERE execution_scope_id=%s AND owner_id=%s",
                (actor.execution_scope_id, actor.actor_id),
            )
            campaigns = list(cursor.fetchall())
            products = request.get("product_scope")
            if products is None:
                products = sorted({c["product_id"] for c in campaigns})
            if not isinstance(products, list) or not 1 <= len(products) <= 100:
                raise StateError("invalid_product_scope", 422)
            for product in products:
                self._resource(cursor, actor, _text(product, "product_id", 64))
            if len(set(products)) != len(products):
                raise StateError("invalid_product_scope", 422)
            budget = request.get("planned_budget_cents")
            if budget is None:
                budget = sum(
                    c["budget_cents"]
                    for c in observation["campaigns"]
                    if c["product_id"] in products
                )
            context = {
                "goal": objective,
                "observation_id": observation["observation_id"],
                "recommendation_snapshot": self._recommendation_state(cursor, actor),
                "plan_meta": {
                    "plan_id": uuid.uuid4().hex,
                    "version": previous["version"] + 1 if previous else 1,
                    "parent_plan_id": previous["plan_id"] if previous else None,
                    "parent_plan_version": previous["version"] if previous else None,
                    "actor_id": actor.actor_id,
                    "agent_run_id": run["agent_run_id"],
                    "scope": actor.execution_scope_id,
                    "execution_scope_id": actor.execution_scope_id,
                    "round_id": observation["round_id"],
                    "period": "scope_lifetime",
                    "objective": objective,
                    "product_scope": products,
                    "planned_budget_cents": _money(budget),
                },
            }
            self._insert(
                cursor,
                "merchant_run_context",
                {
                    "agent_run_id": run["agent_run_id"],
                    "execution_scope_id": actor.execution_scope_id,
                    "actor_id": actor.actor_id,
                    "request_id": request_id,
                    "request_hash": request_hash,
                    "observation_id": observation["observation_id"],
                    "context_json": canonical(context),
                    "created_at": self.clock(),
                },
            )

    def get_merchant_context(self, actor, run_id):
        self.get_run(actor, run_id)
        with self._transaction() as cursor:
            row = self._row(
                cursor, actor, "merchant_run_context", "agent_run_id", run_id
            )
            if row["actor_id"] != actor.actor_id:
                raise StateError("merchant_run_not_found", 404)
            context = json.loads(row["context_json"])
            obs = self._row(
                cursor,
                actor,
                "merchant_observation",
                "observation_id",
                row["observation_id"],
            )
            context["observation"] = json.loads(obs["snapshot_json"])
            context["previous_plan"] = self._latest_plan(cursor, actor)
            cursor.execute(
                "SELECT * FROM merchant_experience WHERE execution_scope_id=%s AND actor_id=%s AND status='APPROVED' ORDER BY approved_at DESC LIMIT 5",
                (actor.execution_scope_id, actor.actor_id),
            )
            context["approved_experiences"] = [_public(r) for r in cursor.fetchall()]
            cursor.execute(
                "SELECT * FROM merchant_plan WHERE agent_run_id=%s", (run_id,)
            )
            plan = cursor.fetchone()
            context["current_plan"] = _public(plan) if plan else None
        context["ads"] = self.snapshot(actor)
        if "recommendation_snapshot" in context:
            context["ads"]["recommendation"] = context["recommendation_snapshot"]
        return context

    def save_merchant_plan(self, lease, spec):
        with self._transaction() as cursor:
            conversation, run = self._locked(cursor, lease)
            cursor.execute(
                "SELECT * FROM merchant_run_context WHERE agent_run_id=%s",
                (run["agent_run_id"],),
            )
            linked = cursor.fetchone()
            if (
                not linked
                or conversation["subject_type"] != "merchant"
                or linked["actor_id"] != conversation["actor_id"]
                or linked["execution_scope_id"] != conversation["execution_scope_id"]
            ):
                raise StateError("merchant_run_not_found", 404)
            context = json.loads(linked["context_json"])
            meta = context["plan_meta"]
            for key in (
                "plan_id",
                "version",
                "actor_id",
                "agent_run_id",
                "objective",
                "product_scope",
                "period",
                "scope",
                "round_id",
                "parent_plan_id",
                "parent_plan_version",
            ):
                if spec.get(key) != meta.get(key):
                    raise StateError("untrusted_merchant_plan_metadata", 422)
            _integer(spec.get("version"), "plan_version", 1)
            if (
                spec.get("execution_scope_id") != linked["execution_scope_id"]
                or spec.get("observation_id") != linked["observation_id"]
            ):
                raise StateError("merchant_plan_scope_mismatch", 403)
            cursor.execute(
                "SELECT * FROM merchant_observation WHERE observation_id=%s",
                (linked["observation_id"],),
            )
            observed = cursor.fetchone()
            if (
                not observed
                or observed["actor_id"] != linked["actor_id"]
                or observed["execution_scope_id"] != linked["execution_scope_id"]
            ):
                raise StateError("merchant_observation_not_found", 404)
            observation = json.loads(observed["snapshot_json"])
            if (
                spec.get("watermark") != observed["watermark"]
                or spec.get("round_id") != observation["round_id"]
            ):
                raise StateError("merchant_observation_mismatch", 422)
            if "evidence_binding_version" in spec:
                # Reuse the planner's pure binding contract; old immutable specs are not rewritten.
                from smartlect.agents.merchant import (
                    EVIDENCE_BINDING_VERSION,
                    SCHEMA_VERSION,
                    InvalidPlan,
                    _facts,
                    bind_selected_facts,
                )

                if (
                    spec["evidence_binding_version"] != EVIDENCE_BINDING_VERSION
                    or spec.get("proposal_schema_version") != SCHEMA_VERSION
                ):
                    raise StateError("unknown_merchant_evidence_contract", 422)
                diagnoses = spec.get("diagnosis")
                if not isinstance(diagnoses, list) or not 1 <= len(diagnoses) <= 6:
                    raise StateError("invalid_merchant_diagnosis", 422)
                facts = _facts({"observation": observation, "plan_meta": meta})
                selected = set()
                for diagnosis in diagnoses:
                    if not isinstance(diagnosis, dict):
                        raise StateError("invalid_merchant_diagnosis", 422)
                    try:
                        bound = bind_selected_facts(
                            diagnosis.get("evidence_ids"), facts
                        )
                    except InvalidPlan:
                        raise StateError(
                            "merchant_evidence_binding_mismatch", 422
                        ) from None
                    if canonical(diagnosis.get("observed_facts")) != canonical(bound):
                        raise StateError("merchant_evidence_binding_mismatch", 422)
                    selected.update(diagnosis["evidence_ids"])
                if spec.get("evidence_ids") != sorted(selected):
                    raise StateError("merchant_evidence_binding_mismatch", 422)
            actions = spec.get("actions")
            if not isinstance(actions, list) or len(actions) > 8:
                raise StateError("invalid_merchant_actions", 422)
            try:
                for action in actions:
                    AdAction.model_validate(action)
            except ValidationError:
                raise StateError("invalid_merchant_actions", 422) from None

            if spec.get("evidence_binding_version"):
                revision = (context.get("recommendation_snapshot") or {}).get(
                    "revision"
                )
                if any(
                    a["action_type"] == "set_recommendation_policy"
                    and a["expected_version"] != revision
                    for a in actions
                ):
                    raise StateError("merchant_recommendation_snapshot_mismatch", 422)
            budgets = {
                c["campaign_id"]: c["budget_cents"]
                for c in observation["campaigns"]
                if c["product_id"] in meta["product_scope"]
            }
            for action in actions:
                if action["action_type"] == "set_recommendation_policy":
                    continue
                if action["campaign_id"] not in budgets:
                    raise StateError("action_resource_outside_observation", 422)
                if action["action_type"] == "set_budget":
                    budgets[action["campaign_id"]] = _money(action["budget_cents"])
            budget = _money(spec.get("planned_budget_cents"))
            if budget > meta["planned_budget_cents"] or budget != sum(budgets.values()):
                raise StateError("merchant_plan_budget_mismatch", 422)
            cursor.execute(
                "SELECT * FROM merchant_plan WHERE agent_run_id=%s",
                (run["agent_run_id"],),
            )
            previous = cursor.fetchone()
            if previous:
                if previous["spec_json"] != canonical(spec):
                    raise StateError("merchant_plan_immutable", 409)
                return _public(previous)
            self._insert(
                cursor,
                "merchant_plan",
                {
                    "plan_id": meta["plan_id"],
                    "version": meta["version"],
                    "execution_scope_id": linked["execution_scope_id"],
                    "actor_id": linked["actor_id"],
                    "agent_run_id": run["agent_run_id"],
                    "observation_id": linked["observation_id"],
                    "parent_plan_id": meta["parent_plan_id"],
                    "parent_plan_version": meta["parent_plan_version"],
                    "status": "VALIDATED",
                    "spec_json": canonical(spec),
                    "diagnosis_json": canonical(spec.get("diagnosis", [])),
                    "action_receipts_json": "[]",
                    "created_at": self.clock(),
                    "updated_at": self.clock(),
                },
            )
            draft = spec.get("experience_draft")
            if draft:
                content = draft.get("content") if isinstance(draft, dict) else draft
                self._insert(
                    cursor,
                    "merchant_experience",
                    {
                        "memory_id": uuid.uuid4().hex,
                        "execution_scope_id": linked["execution_scope_id"],
                        "actor_id": linked["actor_id"],
                        "plan_id": meta["plan_id"],
                        "content": _text(redact_text(content), "experience", 2000),
                        "evidence_ids_json": canonical(spec["evidence_ids"]),
                        "created_at": self.clock(),
                    },
                )
            cursor.execute(
                "SELECT * FROM merchant_plan WHERE plan_id=%s", (meta["plan_id"],)
            )
            return _public(cursor.fetchone())

    def get_plan(self, actor, plan_id):
        _merchant(actor)
        with self._transaction() as cursor:
            row = self._row(cursor, actor, "merchant_plan", "plan_id", plan_id)
            if row["actor_id"] != actor.actor_id:
                raise StateError("plan_not_found", 404)
            return _public(row)

    def recover_completed_plan(self, actor, plan_id, expected_version):
        """Restore committed facts before checking whether new writes remain authorized."""
        _merchant(actor)
        with self._transaction() as cursor:
            self._lock(cursor, actor)
            row = self._row(cursor, actor, "merchant_plan", "plan_id", plan_id)
            if row["actor_id"] != actor.actor_id:
                raise StateError("plan_not_found", 404)
            if _integer(expected_version, "expected_version", 1) != row["version"]:
                raise StateError("plan_version_conflict", 409)
            if row["status"] in {
                "WAIT_OBSERVATION",
                "REVIEWED",
                "PARTIALLY_APPLIED",
                "FAILED",
            }:
                return _public(row)
            if (
                not row["grant_id"]
                or row["lease_until"]
                and row["lease_until"] > self.clock()
            ):
                return None
            plan = _public(row)
            receipts = []
            status = "WAIT_OBSERVATION"
            for index, batch in enumerate(plan_batches(plan)):
                result = self._action_replay(
                    cursor, actor, plan_action_request(plan, index, batch)
                )
                if result is None:
                    cursor.execute(
                        "UPDATE merchant_plan SET action_receipts_json=%s WHERE plan_id=%s",
                        (canonical(receipts), plan_id),
                    )
                    return None
                if result["status"] == "REJECTED":
                    receipts.append(
                        {
                            "batch": index,
                            "command_status": "rejected",
                            "receipt": result,
                        }
                    )
                    status = "PARTIALLY_APPLIED" if index else "FAILED"
                    break
                receipts.append(
                    {
                        "batch": index,
                        "command_status": "business_completed",
                        "receipt": result,
                    }
                )
            cursor.execute(
                "UPDATE merchant_plan SET status=%s,action_receipts_json=%s,lease_token=NULL,lease_until=NULL,updated_at=%s WHERE plan_id=%s",
                (status, canonical(receipts), self.clock(), plan_id),
            )
            cursor.execute("SELECT * FROM merchant_plan WHERE plan_id=%s", (plan_id,))
            return _public(cursor.fetchone())

    def claim_plan(self, actor, plan_id, expected_version):
        _merchant(actor)
        with self._transaction() as cursor:
            self._lock(cursor, actor)
            row = self._row(cursor, actor, "merchant_plan", "plan_id", plan_id)
            if row["actor_id"] != actor.actor_id:
                raise StateError("plan_not_found", 404)
            if _integer(expected_version, "expected_version", 1) != row["version"]:
                raise StateError("plan_version_conflict", 409)
            if row["status"] in {
                "WAIT_OBSERVATION",
                "REVIEWED",
                "PARTIALLY_APPLIED",
                "FAILED",
            }:
                return {"plan": _public(row), "token": None}
            if row["lease_until"] and row["lease_until"] > self.clock():
                raise StateError("plan_busy", 409)
            spec = json.loads(row["spec_json"])
            if not spec["actions"]:
                cursor.execute(
                    "UPDATE merchant_plan SET status='WAIT_OBSERVATION',authorization_json=%s,updated_at=%s WHERE plan_id=%s",
                    (
                        canonical({"required": False, "reason": "no_business_action"}),
                        self.clock(),
                        plan_id,
                    ),
                )
                cursor.execute(
                    "SELECT * FROM merchant_plan WHERE plan_id=%s", (plan_id,)
                )
                return {"plan": _public(cursor.fetchone()), "token": None}
            try:
                # Once execution has started, recovery cannot silently adopt a replacement grant.
                account, grant, envelope = self._grant(
                    cursor, actor, row["grant_id"], owner=True
                )
                if spec["objective"] != envelope["objective"] or not set(
                    spec["product_scope"]
                ) <= set(envelope["product_scope"]):
                    raise StateError("plan_outside_grant", 403)
                if _money(spec["planned_budget_cents"]) > account["budget_cap_cents"]:
                    raise StateError("planned_budget_outside_grant", 403)
                cursor.execute(
                    "SELECT campaign_id,budget_cents FROM ads_campaign WHERE execution_scope_id=%s",
                    (actor.execution_scope_id,),
                )
                budgets = {
                    c["campaign_id"]: c["budget_cents"] for c in cursor.fetchall()
                }
                for action in spec["actions"]:
                    if action["action_type"] not in envelope["allowed_action_types"]:
                        raise StateError("action_outside_grant", 403)
                    if action["action_type"] == "set_recommendation_policy":
                        limits = policy_range(
                            envelope.get("recommendation_policy_range", {})
                        )
                        policy = _fields(
                            action["policy"], ("strategy_version", "group", "config")
                        )
                        _text(policy["strategy_version"], "strategy_version")
                        config = strategy_config(policy["config"])
                        if (
                            not limits
                            or policy["group"] not in limits["groups"]
                            or config["ranking"] not in limits["rankings"]
                            or any(
                                type(v) is not int or not 0 <= v <= limits["max_weight"]
                                for v in config["weights"].values()
                            )
                            or any(
                                type(v) is not int or not 0 <= v <= limits["max_quota"]
                                for v in config["quotas"].values()
                            )
                        ):
                            raise StateError("policy_outside_grant", 403)
                        if actor.execution_scope_id == "store":
                            raise StateError("policy_requires_registered_scope", 403)
                        cursor.execute(
                            "SELECT resource_id FROM execution_resource WHERE execution_scope_id=%s AND resource_type='product'",
                            (actor.execution_scope_id,),
                        )
                        products = {r["resource_id"] for r in cursor.fetchall()}
                        if not products <= set(
                            envelope["product_scope"]
                        ) or not products <= set(spec["product_scope"]):
                            raise StateError("policy_product_scope_outside_grant", 403)
                    else:
                        ca = self._row(
                            cursor,
                            actor,
                            "ads_campaign",
                            "campaign_id",
                            action["campaign_id"],
                            owner=True,
                        )
                        if (
                            ca["product_id"] not in envelope["product_scope"]
                            or ca["product_id"] not in spec["product_scope"]
                        ):
                            raise StateError("product_outside_grant", 403)
                        self._resource(cursor, actor, ca["product_id"])
                        if action["action_type"].endswith("_creative"):
                            cr = self._row(
                                cursor,
                                actor,
                                "ads_creative",
                                "creative_id",
                                action["creative_id"],
                                owner=True,
                            )
                            if cr["campaign_id"] != ca["campaign_id"]:
                                raise StateError("creative_campaign_mismatch", 409)
                        if action["action_type"] == "set_budget":
                            budget = _money(action["budget_cents"])
                            if (
                                abs(budget - ca["budget_cents"])
                                > envelope["max_budget_change_cents"]
                            ):
                                raise StateError("budget_change_outside_grant", 403)
                            if budget < ca["spent_cents"]:
                                raise StateError("budget_below_spent", 409)
                            budgets[ca["campaign_id"]] = budget
                if sum(budgets.values()) > account["budget_cap_cents"] and any(
                    a["action_type"]
                    in {
                        "set_budget",
                        "activate_campaign",
                        "activate_creative",
                        "resume_campaign",
                        "resume_creative",
                    }
                    for a in spec["actions"]
                ):
                    raise StateError("aggregate_budget_exceeds_grant", 403)
                authorization = {
                    "within_grant": True,
                    "grant_id": grant["grant_id"],
                    "envelope_hash": grant["envelope_hash"],
                    "checked_at": iso(self.clock()),
                }
                approved_snapshot = json.loads(grant["plan_snapshot_json"])
                if (
                    grant["initial_plan_id"] == row["plan_id"]
                    and grant["initial_plan_version"] == row["version"]
                    and approved_snapshot.get("merchant_plan_spec") == spec
                    and approved_snapshot.get("approval_resource_transitions")
                ):
                    authorization.update(
                        approval_snapshot_hash=grant["plan_snapshot_hash"],
                        approval_resource_transitions=approved_snapshot[
                            "approval_resource_transitions"
                        ],
                    )
            except StateError as error:
                authorization = {
                    "within_grant": False,
                    "reason": error.code,
                    "checked_at": iso(self.clock()),
                }
                applied = any(
                    r.get("command_status") == "business_completed"
                    and r.get("receipt", {}).get("status") == "APPLIED"
                    for r in json.loads(row["action_receipts_json"])
                )
                status = "PARTIALLY_APPLIED" if applied else "WAIT_APPROVAL"
                cursor.execute(
                    "UPDATE merchant_plan SET status=%s,authorization_json=%s,updated_at=%s WHERE plan_id=%s",
                    (status, canonical(authorization), self.clock(), plan_id),
                )
                cursor.execute(
                    "SELECT * FROM merchant_plan WHERE plan_id=%s", (plan_id,)
                )
                return {"plan": _public(cursor.fetchone()), "token": None}
            token = uuid.uuid4().hex
            cursor.execute(
                "UPDATE merchant_plan SET status='EXECUTING',grant_id=%s,envelope_hash=%s,authorization_json=%s,lease_token=%s,lease_until=%s,updated_at=%s WHERE plan_id=%s",
                (
                    grant["grant_id"],
                    grant["envelope_hash"],
                    canonical(authorization),
                    token,
                    self.clock() + timedelta(seconds=30),
                    self.clock(),
                    plan_id,
                ),
            )
            cursor.execute("SELECT * FROM merchant_plan WHERE plan_id=%s", (plan_id,))
            return {"plan": _public(cursor.fetchone()), "token": token}

    def finish_plan(self, actor, plan_id, token, status, receipts):
        if status not in {
            "EXECUTING",
            "WAIT_OBSERVATION",
            "PARTIALLY_APPLIED",
            "FAILED",
        }:
            raise StateError("invalid_plan_status", 422)
        with self._transaction() as cursor:
            self._lock(cursor, actor)
            cursor.execute(
                "UPDATE merchant_plan SET status=%s,action_receipts_json=%s,lease_token=NULL,lease_until=NULL,updated_at=%s WHERE plan_id=%s AND actor_id=%s AND execution_scope_id=%s AND lease_token=%s",
                (
                    status,
                    canonical(receipts),
                    self.clock(),
                    plan_id,
                    actor.actor_id,
                    actor.execution_scope_id,
                    token,
                ),
            )
            if cursor.rowcount != 1:
                raise StateError("plan_execution_fenced", 409)
            cursor.execute("SELECT * FROM merchant_plan WHERE plan_id=%s", (plan_id,))
            return _public(cursor.fetchone())

    def approve_experience(
        self, actor, memory_id, expected_version, reviewed_content=None
    ):
        _merchant(actor)
        expected_version = _integer(expected_version, "expected_version", 1)
        with self._transaction() as cursor:
            self._lock(cursor, actor)
            row = self._row(
                cursor, actor, "merchant_experience", "memory_id", memory_id
            )
            if row["actor_id"] != actor.actor_id:
                raise StateError("experience_not_found", 404)
            if reviewed_content is None:
                plan = self._row(
                    cursor, actor, "merchant_plan", "plan_id", row["plan_id"]
                )
                draft = json.loads(plan["spec_json"])["experience_draft"]
                reviewed_content = (
                    draft.get("content") if isinstance(draft, dict) else draft
                )
            content = _text(
                redact_text(_text(reviewed_content, "reviewed_content", 2000)),
                "reviewed_content",
                2000,
            )
            if (
                row["status"] == "APPROVED"
                and expected_version == row["version"] - 1
                and content == row["content"]
            ):
                return _public(row)
            if expected_version != row["version"] or row["status"] != "DRAFT":
                raise StateError("experience_version_conflict", 409)
            cursor.execute(
                "UPDATE merchant_experience SET content=%s,status='APPROVED',version=version+1,approved_by=%s,approved_at=%s WHERE memory_id=%s",
                (content, actor.actor_id, self.clock(), memory_id),
            )
            cursor.execute(
                "SELECT * FROM merchant_experience WHERE memory_id=%s", (memory_id,)
            )
            return _public(cursor.fetchone())
