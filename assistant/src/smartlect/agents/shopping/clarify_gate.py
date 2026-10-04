"""低置信度澄清闸（deterministic clarification gate）。

借鉴 EchoMind `_needs_clarification`：低置信度先澄清、不瞎猜。Smartlect 版
保持确定性、零误报原则，只保留两条「模型无论如何都行动不了」的判据——
普通模糊问句仍走正常流程（任务槽抽取与守卫链已有兜底）。

用法：run_shopping 组装系统提示时调用；命中则注入一行引导（优先产出
request_kind=clarify 的终答，而不是烧预算穷举工具试探），并发 decision 事件。
闸门只提示、不强制改判——终答编译仍由 answer_node 守卫链决定，
不新增任何对话往返（面试点：Agent 置信度规则 + 何时向用户确认）。
"""
import re

_COMPARE_SIGNAL = re.compile(r'比较|对比|哪个更|哪一个好|区别')
_PAIR_SEPARATOR = re.compile(r'和|还是|VS|vs|与')
# 仅由请求功能词构成的问句（如「推荐一下」「帮我来一个」）——不含任何内容词。
_BARE_REQUEST_CHARS = set('帮我请推荐买来个一下单想要有没有看找随便吧呢吗，。？ ·,。')


def needs_clarification(question, mission):
    """返回 (是否建议澄清, 机器可读理由, 需补齐字段的中文说明)。

    判据 A comparison_targets_missing：比较请求，但任务槽没有比较目标、
      问句里也没有「和/还是/vs」这类内联配对标记——两个对照对象无从获得。
    判据 B bare_request：问句仅由请求功能词构成，没有任何内容词——
      连选品对象或用途都没有。
    """
    text = (question or '').strip()
    mission = mission or {}
    if _COMPARE_SIGNAL.search(text) and not (mission.get('comparison_targets') or []):
        if not _PAIR_SEPARATOR.search(text):
            return True, 'comparison_targets_missing', '要比较的具体对象（至少两个）'
    if text and set(text) <= _BARE_REQUEST_CHARS and len(text) >= 2:
        return True, 'bare_request', '想要的商品或用途'
    return False, None, None


def clarify_hint(reason, missing):
    return (f'本轮澄清闸（确定性判据 {reason}）：用户目标信息不足，'
            f'优先产出 request_kind=clarify 的终答向用户补齐「{missing}」，'
            '不要穷举工具试探。')
