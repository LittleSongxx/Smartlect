"""Smartlect Shopping agent package (split from the single-module era).

Layout: policy (frozen text/labels) → contract (final-answer schema/exceptions) →
guardrails (pure heuristics/budget) → compile (deterministic closeouts) →
observations (tool projections) → session (one bounded run) → graph (wiring).
This __init__ re-exports the historical single-module surface; import from the
submodules for new code.
"""
from .policy import (BOOTSTRAP_TOOLS, EMPTY_EVIDENCE_ANSWER, EXCEPTION_KINDS, MODEL_CALL_LIMIT,
                     PRODUCT_UNCOVERED_ANSWER, PROMPT_VERSION, PROPOSAL_CONFIRMATION,
                     PROVIDER_FAULT_ANSWER, REQUEST_KINDS, SCHEMA_VERSION, STATE_SELF_ANSWER_TOOLS,
                     SYSTEM_POLICY_BODY)
from .contract import (BudgetExceeded, FinalAnswer, GuardViolation, extract_streamed_answer,
                       final_answer_response_format, final_answer_schema)
from .guardrails import (allow_retrieval_rewrite, answer_defers_ticket_to_user, answer_offers_human_transfer,
                         answer_states_human_necessity, bind_sole_observed_sku,
                         coerce_observed_fact_grounding, keep_uncovered_leftovers,
                         looks_like_catalog_fact_question, looks_like_irreconcilable_sources,
                         looks_like_product_unique_fact, looks_like_service_request,
                         no_business_claim_has_store_conclusion, rejected_search_data,
                         retrieval_budget_action, salvage_unstructured_fact_answer,
                         store_policy_allows_empty_citations)
from .compile import (attach_proposal_confirmation, classify_evidence, close_degraded_turn,
                      compile_decision, controller_fallback_result, empty_evidence_result,
                      proposal_intent_note, salvage_observed_fact_closeout, store_side_denials,
                      template_observed_catalog_result)
from .knowledge_reexport import misses_utterance_constraints  # noqa: F401 — legacy surface
from .observations import constraint_echo, knowledge_observation, product_observation, sku_items, \
    sku_observation, sku_obeys_request
from .session import bounded_messages, run_shopping
from .graph import RunState, build_shopping_graph, route_shopping_model

__all__ = [
    name for name in dir()
    if not name.startswith('_')
]
