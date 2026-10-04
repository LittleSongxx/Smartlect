"""Read only the reviewed, packaged business skills. Documents cannot install code."""
import json
from importlib.resources import files

from smartlect.db import canonical

USER_SKILLS = ("shopping_advice", "support_policy", "order_service")

# 已加载 Skill 指令注入系统提示的字符预算：防流程文本膨胀侵蚀主上下文
# （当前三个 Skill 全量约 1.8K 字符，预算留足增长余量；超出部分截断并披露）。
SKILL_PROMPT_CHAR_LIMIT = 6000


def load_skill(skill_id, *, domain="shopping"):
    allowed = USER_SKILLS if domain == "shopping" else ()
    if skill_id not in allowed:
        raise ValueError("skill_not_allowed")
    return json.loads(files("smartlect").joinpath("skills", skill_id + ".json").read_text())


def catalog(*, domain="shopping"):
    allowed = USER_SKILLS if domain == "shopping" else ()
    return [{key: value for key, value in load_skill(name, domain=domain).items() if key in {"skill_id", "version", "intents"}}
            for name in allowed]


def suggest_skills(question, *, domain="shopping", limit=2, entries=None):
    """确定性 Skill 预告：按各 Skill 的 intents 关键词给问句打分排序（无 LLM）。

    预告不改变加载语义——load_skill 仍由模型显式调用并记入台账；预告只是把
    「本轮该优先套用哪份流程」作为信号注入系统提示（Skill 渐进式披露的轻量版，
    对齐 docs/adr/0012 的 EchoMind SkillManager 借鉴：关键词双维匹配、不烧调用）。
    整词命中计 2 分，词尾两字（中文名词重心）命中计 1 分。
    entries 允许复用调用方已取好的 catalog()，省一次重复读盘。
    """
    text = (question or '').lower()
    scored = []
    for entry in (entries if entries is not None else catalog(domain=domain)):
        score = 0
        for intent in entry['intents']:
            key = intent.lower()
            if key in text:
                score += 2
            elif len(key) >= 2 and key[-2:] in text:
                score += 1
        if score:
            scored.append((score, entry['skill_id']))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [skill_id for _, skill_id in scored[:limit]]


def render_loaded_skills(skills, *, budget=SKILL_PROMPT_CHAR_LIMIT):
    """已加载 Skill 指令的注入渲染 + 字符预算截断。

    超预算的 Skill 不注入正文但披露名单——模型仍可 load_skill 单独获取，
    截断是保护主上下文，不是静默丢弃。
    """
    parts, used, dropped = [], 0, []
    for name, skill in skills.items():
        body = canonical({name: skill['instructions']})
        if parts and used + len(body) > budget:
            dropped.append(name)
            continue
        parts.append(body)
        used += len(body)
    rendered = ''.join(parts)
    if dropped:
        rendered += f'（字符预算截断，未注入：{"、".join(dropped)}；可 load_skill 单独获取）'
    return rendered
