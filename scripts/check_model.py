#!/usr/bin/env python3
"""Real authorized provider smoke; output contains synthetic checks and sanitized metadata only."""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from runtime import ROOT, model_env
from smartlect.provider import Provider, ProviderError
from smartlect.tools import SearchArgs, tool_schema


async def check(output, only=None):
    if output.exists():
        raise ValueError('Use a new output path; prior provider evidence is preserved')
    config = model_env()
    provider = Provider(config)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "model_mode": "live",
              "scope": "provider protocol smoke using synthetic inputs; no business/model-quality claim",
              "model_id": provider.model_id, "max_attempts": 2, "attempt_timeout_seconds": 25,
              "api_concurrency": 2, "enable_thinking": False, "enable_search": False,
              "vendor_builtin_tools": False, "capabilities": {}, "calls": []}
    report["source_sha256"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        "growth/src/smartlect/provider.py", "growth/src/smartlect/tools.py", "scripts/check_model.py", "growth/requirements.lock")}

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    async def run(name, fn):
        traces = []
        try:
            details = await fn(traces.append)
            report["capabilities"][name] = {"passed": True, **details}
        except ProviderError as exc:
            report["capabilities"][name] = {"passed": False, "error_code": exc.code,
                                            "http_status": exc.http_status}
        except (AssertionError, ValueError, KeyError, TypeError):
            report["capabilities"][name] = {"passed": False, "error_code": "unexpected_protocol_result"}
        report['capabilities'][name]['required_for_runtime'] = name != 'structured_tools'
        report["calls"].extend({"capability": name, **trace} for trace in traces)
        save()
        print(name + ": " + ("passed" if report["capabilities"][name]["passed"] else "failed"), flush=True)

    async def text(trace):
        result = await provider.chat([{"role": "user", "content": "请只回复 SMARTLECT_OK。"}],
                                     max_tokens=32, on_trace=trace, prompt_version="provider-smoke-text-v1")
        assert "SMARTLECT_OK" in result["message"]["content"]
        return {"nonempty_text": True}

    tool = {"type": "function", "function": {"name": "lookup_demo_policy",
            "description": "Look up the synthetic Smartlect demo policy. Always call before answering a policy question.",
            "parameters": {"type": "object", "properties": {"topic": {"type": "string", "enum": ["refund"]}},
                           "required": ["topic"], "additionalProperties": False}}}

    async def tools(trace):
        messages = [{"role": "user", "content": "请调用 lookup_demo_policy 查询合成演示的 refund 政策，不能凭记忆回答。"}]
        result = await provider.chat(messages, tools=[tool], on_trace=trace, max_tokens=128,
                                     prompt_version="provider-smoke-tools-v1")
        calls = result["message"].get("tool_calls")
        assert len(calls) == 1 and calls[0]["function"]["name"] == "lookup_demo_policy"
        assert json.loads(calls[0]["function"]["arguments"]) == {"topic": "refund"}
        messages.extend([result["message"], {"role": "tool", "tool_call_id": calls[0]["id"],
                                           "content": '{"synthetic":true,"policy":"DEMO_REFUND_REQUIRES_CONFIRMATION"}'}])
        answer = await provider.chat(messages, tools=[tool], on_trace=trace, max_tokens=128,
                                     prompt_version="provider-smoke-tools-result-v1")
        assert answer["message"]["content"] and not answer["message"].get("tool_calls")
        return {"function_arguments_valid": True, "tool_result_roundtrip": True}

    async def structured(trace):
        schema = {"type": "json_schema", "json_schema": {"name": "smartlect_smoke", "strict": True,
                  "schema": {"type": "object", "properties": {"brand": {"type": "string", "enum": ["Smartlect"]},
                              "synthetic": {"type": "boolean", "enum": [True]}},
                             "required": ["brand", "synthetic"], "additionalProperties": False}}}
        result = await provider.chat([{"role": "user", "content": "Return JSON with brand Smartlect and synthetic true."}],
                                     response_format=schema, max_tokens=64, on_trace=trace,
                                     prompt_version="provider-smoke-json-schema-v1", schema_version="smoke-v1")
        assert json.loads(result["message"]["content"]) == {"brand": "Smartlect", "synthetic": True}
        return {"strict_json_schema": True}

    async def structured_tools(trace):
        from smartlect.agents.shopping import FinalAnswer
        schema = FinalAnswer.model_json_schema()
        schema['required'] = list(schema['properties'])
        for field in schema['properties'].values():
            field.pop('default', None)
        response_format = {'type':'json_schema','json_schema':{
            'name':'smartlect_final_answer','strict':True,'schema':schema}}
        messages=[{'role':'user','content':'这是协议测试。先调用lookup_demo_policy查询refund，然后按给定JSON Schema回答；不生成订单。引用和商品数组为空。'}]
        first=await provider.chat(messages,tools=[tool],response_format=response_format,on_trace=trace,
            max_tokens=512,prompt_version='provider-smoke-structured-tools-v1')
        report.setdefault('protocol_messages',[]).append({key:first['message'].get(key) for key in ('role','content','tool_calls')})
        calls=first['message'].get('tool_calls') or []
        assert len(calls)==1 and calls[0]['function']['name']=='lookup_demo_policy'
        assert json.loads(calls[0]['function']['arguments'])=={'topic':'refund'}
        messages.extend([first['message'],{'role':'tool','tool_call_id':calls[0]['id'],
            'content':'{"synthetic":true,"policy":"DEMO_REFUND_REQUIRES_CONFIRMATION"}'}])
        result=await provider.chat(messages,tools=[tool],response_format=response_format,on_trace=trace,
            max_tokens=512,prompt_version='provider-smoke-structured-tools-v1')
        report['protocol_messages'].append({key:result['message'].get(key) for key in ('role','content','tool_calls')})
        assert not result['message'].get('tool_calls')
        answer=FinalAnswer.model_validate_json(result['message']['content'])
        assert not answer.citation_chunk_ids and not answer.selected_sku_keys
        return {'tool_call_then_strict_final_json':True,'final_field_names':list(json.loads(result['message']['content']))}

    async def final_tool(trace):
        from smartlect.agents.shopping import FinalAnswer, final_answer_schema
        final=final_answer_schema()
        messages=[{'role':'user','content':'这是合成协议测试，不生成订单。先调用lookup_demo_policy查询refund；拿到结果后只调用finish_answer提交回答，引用和商品列表为空，不输出正文或代码块。'}]
        first=await provider.chat(messages,tools=[tool,final],tool_choice='required',on_trace=trace,max_tokens=512,
            prompt_version='provider-smoke-final-tool-v2')
        report.setdefault('final_tool_messages',[]).append({key:first['message'].get(key) for key in ('role','content','tool_calls')})
        calls=first['message'].get('tool_calls') or []
        assert len(calls)==1 and calls[0]['function']['name']=='lookup_demo_policy'
        messages.extend([first['message'],{'role':'tool','tool_call_id':calls[0]['id'],
            'content':'{"synthetic":true,"policy":"DEMO_REFUND_REQUIRES_CONFIRMATION"}'}])
        result=await provider.chat(messages,tools=[tool,final],tool_choice='required',on_trace=trace,max_tokens=512,
            prompt_version='provider-smoke-final-tool-v2')
        report['final_tool_messages'].append({key:result['message'].get(key) for key in ('role','content','tool_calls')})
        calls=result['message'].get('tool_calls') or []
        assert len(calls)==1 and calls[0]['function']['name']=='finish_answer'
        answer=FinalAnswer.model_validate_json(calls[0]['function']['arguments'])
        assert not answer.citation_chunk_ids and not answer.selected_sku_keys
        return {'tool_then_structured_final_function':True,'business_side_effects':False}

    async def integer_tool(trace):
        definition = {'type': 'function', 'function': {'name': 'search_skus',
                      'description': 'Search synthetic SKU; prices are integer cents.', 'parameters': tool_schema(SearchArgs)}}
        result = await provider.chat([{'role': 'user', 'content': '请调用search_skus，query为数码，价格上限20元=2000分，limit=4。'}],
                                     tools=[definition], on_trace=trace, max_tokens=128,
                                     prompt_version='provider-smoke-integer-tool-v1')
        calls = result['message'].get('tool_calls')
        assert len(calls) == 1 and calls[0]['function']['name'] == 'search_skus'
        args = SearchArgs.model_validate(json.loads(calls[0]['function']['arguments']))
        assert args.max_price_cents == 2000 and args.limit == 4
        return {'optional_integer_kept_numeric': True, 'strict_backend_validation': True}

    async def stream(trace):
        deltas = []
        result = await provider.chat([{"role": "user", "content": "请用一句中文说明这是一条合成测试消息。"}],
                                     stream=True, on_delta=deltas.append, on_trace=trace, max_tokens=64,
                                     prompt_version="provider-smoke-stream-v1")
        assert deltas and "".join(deltas) == result["message"]["content"]
        return {"content_delta_count": len(deltas), "usage_received": result["usage"]["total_tokens"] is not None}

    async def errors(trace):
        invalid = Provider({**config, "SMARTLECT_MODEL_API_KEY": "smartlect-intentionally-invalid-smoke-key"})
        try:
            await invalid.chat([{"role": "user", "content": "synthetic auth check"}], max_attempts=1,
                               on_trace=trace, max_tokens=1, prompt_version="provider-smoke-auth-error-v1")
        except ProviderError as exc:
            assert exc.code == "model_http_error" and exc.http_status in {401, 403}
            assert len(exc.attempts) == 1
            return {"invalid_auth_rejected": True, "http_status": exc.http_status, "attempts": 1}
        raise AssertionError("invalid auth unexpectedly accepted")

    async def embedding(trace):
        result = await provider.embed(["合成演示：退款须由本人确认。", "合成演示：杯子可用于饮水。"], on_trace=trace)
        vectors = result["embeddings"]
        assert len(vectors) == 2 and all(math.isfinite(v) for row in vectors for v in row)
        return {"model_id": result["metadata"]["model_id"], "dimensions": result["metadata"]["dimensions"],
                "batch_size": len(vectors), "nonzero_finite_vectors": all(any(row) for row in vectors)}

    for name, fn in (("text", text), ("tools", tools), ("integer_tool", integer_tool), ("structured_json", structured), ("structured_tools", structured_tools), ("final_tool", final_tool),
                     ("stream", stream), ("error_handling", errors), ("embedding", embedding)):
        if only and name != only:
            continue
        await run(name, fn)
    required=[item for item in report['capabilities'].values() if only or item['required_for_runtime']]
    report["passed"] = bool(required) and all(item["passed"] for item in required)
    report["actual_http_attempts"] = len(report["calls"])
    report["rerank"] = {"status": "not_executed", "reason": "not an F2 gate; embedding/RRF first"}
    save()
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/f2-provider-capabilities.json")
    parser.add_argument('--only', choices=['text','tools','integer_tool','structured_json','structured_tools','final_tool','stream','error_handling','embedding'])
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check(args.output,args.only)))
