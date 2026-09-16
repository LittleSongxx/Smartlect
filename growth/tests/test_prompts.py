"""Prompt template store: validation, fallback resolution, version labelling, seeding."""
import asyncio
import json
import unittest
import uuid
from unittest.mock import MagicMock, Mock

from smartlect.auth import ActorContext
from smartlect.business_skills import load_skill
from smartlect.prompts import PromptStore, _code_version, resolve_skill, resolve_system
from smartlect.state import StateError

ACTOR = ActorContext(subject_type="merchant", actor_id="boss", session_id="s",
                     permissions=("admin:legacy",), execution_scope_id="scope")


def mock_connect(rows=None):
    connection, cursor = MagicMock(), MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.rowcount = 1
    cursor.fetchall.return_value = rows or []
    cursor.fetchone.return_value = None
    return Mock(return_value=connection), cursor


PACKAGED = load_skill("support_policy")


class ValidationTests(unittest.TestCase):
    def test_skill_body_must_match_packaged_structure_and_id(self):
        connect, cursor = mock_connect()
        cursor.fetchall.return_value = [{"version": 1}]  # series locked FOR UPDATE -> next is 2
        store = PromptStore(connect)
        good = json.dumps(PACKAGED, ensure_ascii=False)
        row = store.create_version(ACTOR, "shopping", "skill", "support_policy", good)
        self.assertEqual(row["version"], 2)

        broken = {**PACKAGED, "skill_id": "other"}
        with self.assertRaises(StateError):
            store.create_version(ACTOR, "shopping", "skill", "support_policy", json.dumps(broken))
        with self.assertRaises(StateError):
            store.create_version(ACTOR, "shopping", "skill", "support_policy", "not json")
        with self.assertRaises(StateError):
            store.create_version(ACTOR, "shopping", "skill", "brand_new_skill", good)  # no new skills via UI
        with self.assertRaises(StateError):
            store.create_version(ACTOR, "shopping", "system_prompt", "system", "x" * 17000)

    def test_system_prompt_validation_rejects_blank(self):
        connect, _ = mock_connect()
        with self.assertRaises(StateError):
            PromptStore(connect).create_version(ACTOR, "shopping", "system_prompt", "system", "  ")

    def test_skill_edit_cannot_widen_the_tool_surface(self):
        connect, cursor = mock_connect()
        cursor.fetchall.return_value = [{"version": 1}]
        store = PromptStore(connect)
        # Narrowing is allowed (the page may retire a tool), adding a name the packaged
        # skill never had is not: the agent's callable set is built from this very list.
        narrowed = {**PACKAGED, "tools": PACKAGED["tools"][:1]}
        self.assertEqual(store.create_version(ACTOR, "shopping", "skill", "support_policy",
                                              json.dumps(narrowed, ensure_ascii=False))["version"], 2)
        for tools in (PACKAGED["tools"] + ["propose_order"], ["propose_order"], "get_my_orders", [1]):
            widened = {**PACKAGED, "tools": tools}
            with self.assertRaises(StateError) as caught:
                store.create_version(ACTOR, "shopping", "skill", "support_policy",
                                     json.dumps(widened, ensure_ascii=False))
            self.assertEqual(caught.exception.code, "skill_tools_not_authorized")


class ResolutionTests(unittest.TestCase):
    def test_fallback_when_db_unavailable_or_empty(self):
        body, label = resolve_system(None, "shopping", "DEFAULT", "shopping-react-v24")
        self.assertEqual((body, label), ("DEFAULT", "shopping-react-v24"))

        def boom():
            raise RuntimeError("db down")
        connect = boom
        body, label = resolve_system(connect, "shopping", "DEFAULT", "shopping-react-v24")
        self.assertEqual((body, label), ("DEFAULT", "shopping-react-v24"))

    def test_active_row_returns_body_with_versioned_label(self):
        connect, cursor = mock_connect()
        cursor.fetchone.return_value = {"body": "新策略文本", "version": 25}
        body, label = resolve_system(connect, "shopping", "DEFAULT", "shopping-react-v24")
        self.assertEqual(body, "新策略文本")
        self.assertEqual(label, "shopping-react-v25")

    def test_resolve_skill_prefers_valid_db_row_and_falls_back(self):
        connect, cursor = mock_connect()
        edited = {**PACKAGED, "instructions": "新的流程说明"}
        cursor.fetchone.return_value = {"body": json.dumps(edited, ensure_ascii=False)}
        self.assertEqual(resolve_skill(connect, "shopping", "support_policy")["instructions"], "新的流程说明")

        cursor.fetchone.return_value = {"body": "{broken json"}
        self.assertEqual(resolve_skill(connect, "shopping", "support_policy")["instructions"],
                         PACKAGED["instructions"])
        self.assertEqual(resolve_skill(None, "shopping", "support_policy")["version"], PACKAGED["version"])

    def test_code_version_extracts_trailing_integer(self):
        self.assertEqual(_code_version("shopping-react-v24"), 24)
        self.assertEqual(_code_version("merchant-plan-v19"), 19)
        self.assertEqual(_code_version("no-digits"), 1)


class SeedTests(unittest.TestCase):
    def test_seed_inserts_code_defaults_only_when_absent(self):
        from smartlect import prompts
        prompts.register_default("shopping", "system_prompt", "system", "种子策略文本", version=24)
        connect, cursor = mock_connect()  # COALESCE(MAX(version),0) -> 0 -> template absent
        cursor.fetchone.return_value = {"latest": 0}
        PromptStore(connect).seed_defaults()
        inserts = [call for call in cursor.execute.call_args_list
                   if "INSERT INTO prompt_template" in call.args[0]]
        self.assertGreater(len(inserts), 0)
        seeded = [call for call in inserts if "种子策略文本" in call.args[1]]
        self.assertTrue(seeded)  # absent templates seed as active
        self.assertEqual(seeded[0].args[1][6], "active")

        cursor.execute.call_args_list.clear()
        cursor.fetchone.return_value = {"latest": 24}  # same version stored -> no insert
        PromptStore(connect).seed_defaults()
        self.assertEqual([call for call in cursor.execute.call_args_list
                          if "INSERT INTO prompt_template" in call.args[0]], [])

    def test_seed_surfaces_newer_code_text_as_draft_without_switching(self):
        from smartlect import prompts
        prompts.register_default("shopping", "system_prompt", "system", "新一代策略文本", version=25)
        connect, cursor = mock_connect()
        cursor.fetchone.return_value = {"latest": 24}  # code moved on, console holds v24
        PromptStore(connect).seed_defaults()
        inserts = [call for call in cursor.execute.call_args_list
                   if "INSERT INTO prompt_template" in call.args[0] and "新一代策略文本" in call.args[1]]
        self.assertEqual(len(inserts), 1)
        # A draft keeps the running text untouched until an operator activates it.
        self.assertEqual(inserts[0].args[1][6], "draft")
        self.assertIn("v25", inserts[0].args[1][5])


if __name__ == "__main__":
    unittest.main()
