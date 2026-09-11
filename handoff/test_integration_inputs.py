"""F0 input boundary checks: run with growth/.venv-f0/bin/python."""
import io
import unittest

from dotenv import dotenv_values
from freeze_integration import AI, FRONT, group_for
from migrate_model_env import select_model_fields
from verify_package import within, ROOT


class IntegrationInputsTest(unittest.TestCase):
    def test_export_selection_and_paths(self):
        for path in (AI + "app/main.py", AI + "prompts/agent.txt", FRONT + "AI_Shop-web/package-lock.json"):
            self.assertIsNotNone(group_for(path))
        for path in (AI + ".env", AI + ".env.example", AI + "evaluation-evidence/log.json",
                     AI + "evaluation/datasets/gold.jsonl", FRONT + "AI_Shop-web/scripts/deploy-web.sh",
                     FRONT + "AI_Shop-web/public/simlect-origin/index.html"):
            self.assertIsNone(group_for(path))
        for path in ("../escape", "/outside", "x/../../outside", "C:\\data"):
            with self.assertRaises(ValueError):
                within(ROOT, path)

    def test_only_model_fields_and_no_expansion(self):
        values = dotenv_values(stream=io.StringIO(
            'LLM_API_KEY="synthetic-$(touch /tmp/never-run)"\n'
            'LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1\n'
            'LLM_MODEL=expensive-model\nMYSQL_PASSWORD=secret\nINTERNAL_TOKEN=secret\n'), interpolate=False)
        selected = select_model_fields(values)
        self.assertEqual(set(selected), {"SMARTLECT_MODEL_API_KEY", "SMARTLECT_MODEL_BASE_URL", "SMARTLECT_MODEL_ID"})
        self.assertEqual(selected["SMARTLECT_MODEL_ID"], "qwen3.7-plus")
        self.assertEqual(selected["SMARTLECT_MODEL_API_KEY"], values["LLM_API_KEY"])
        with self.assertRaises(ValueError):
            select_model_fields({**values, "LLM_API_KEY": "${INTERNAL_TOKEN}"})

    def test_reject_application_and_credential_urls(self):
        for url in ("http://127.0.0.1:8000", "https://user:secret@dashscope.aliyuncs.com/v1",
                    "https://dashscope.aliyuncs.com.evil.test/v1", "https://dashscope.aliyuncs.com/v1?key=secret"):
            with self.assertRaises(ValueError):
                select_model_fields({"LLM_API_KEY": "synthetic", "LLM_BASE_URL": url})


if __name__ == "__main__":
    unittest.main()
