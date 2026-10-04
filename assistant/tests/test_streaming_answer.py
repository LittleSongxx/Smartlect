"""真 token 流式的核心不变量：部分 JSON 流的 answer 抽取必须逐次前缀扩展。

session.on_token 依赖 extract_streamed_answer 从部分缓冲里抽 answer 字段并
按增量发 message_delta——若任何一步的抽取结果不是上一步的扩展，前端拼接
就会出现乱序/重复。本测试把该性质锁死在字符级逐位喂入上。
"""
import json
import unittest

from smartlect.agents.shopping.contract import extract_streamed_answer

FULL = json.dumps({
    "answer": "这款键盘支持三模连接。\n电池续航约 400 小时，含 \"充电线\" 一根。",
    "request_kind": "inquire_fact",
    "handoff_requested": False,
    "grounding": "store_policy",
    "citation_chunk_ids": ["c1"],
    "selected_sku_keys": [],
    "requires_clarification": False,
}, ensure_ascii=False)


class ExtractStreamedAnswerTests(unittest.TestCase):
    def test_incremental_extraction_is_prefix_extending(self):
        final_answer = json.loads(FULL)["answer"]
        previous = ""
        for size in range(1, len(FULL) + 1):
            partial = extract_streamed_answer(FULL[:size])
            if partial is None or partial == "":
                continue
            # 每次抽出的文本必须是上一次的扩展（前缀不变，只追加）
            self.assertTrue(partial.startswith(previous),
                            f'缓冲 {size} 字符时抽取结果不是前缀扩展: {previous!r} -> {partial!r}')
            self.assertTrue(final_answer.startswith(partial))
            previous = partial
        self.assertEqual(previous, final_answer)

    def test_complete_buffer_returns_full_answer_field(self):
        self.assertEqual(extract_streamed_answer(FULL), json.loads(FULL)["answer"])

    def test_buffer_before_answer_key_returns_none(self):
        head = FULL[:FULL.index('"answer"')]
        self.assertIsNone(extract_streamed_answer(head))

    def test_non_json_buffer_returns_stripped_text(self):
        # 非契约 JSON 的文本轮：session 侧已用 startswith('{') 门控不流式，
        # 函数本身保持原有回退语义（返回去空白文本）。
        self.assertEqual(extract_streamed_answer('  普通文本回答  '), '普通文本回答')

    def test_throttle_contract_piece_concatenation(self):
        # 模拟 on_token 的节流切片：任意时刻发出的 piece 序列按序拼接
        # 必须等于当时的抽取结果（前端 replayedDeltas 拼接的正确性前提）。
        emitted, already = [], 0
        for size in range(1, len(FULL) + 1):
            partial = extract_streamed_answer(FULL[:size])
            if partial is None:
                continue
            if len(partial) - already >= 5:  # 测试用更小的字符闸
                emitted.append(partial[already:])
                already = len(partial)
        partial_full = extract_streamed_answer(FULL)
        if len(partial_full) - already > 0:
            emitted.append(partial_full[already:])
        self.assertEqual(''.join(emitted), json.loads(FULL)["answer"])


if __name__ == "__main__":
    unittest.main()
