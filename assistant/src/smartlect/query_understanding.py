"""查询理解收口（组件 3）：确定性指代补全与独立问句透传。

设计约束（对齐 ADR-0013 的守卫分层哲学）：
- 纯确定性实现——无 LLM 调用、零预算消耗，每一步变化可测试、可归因；
- 指代式短问句（"那这个保修多久"）用任务槽（mission）补全检索上下文；
- 独立完整问句必须原样透传——把订单号/商品名塞进通用政策问句会让政策
  检索失配（mewhelp ch06 的 coref 纪律：负例与正例同等重要）；
- 无可补全上下文时回落原句：改写是增益不是依赖，失败路径等于现状行为。
"""
import re

# 指代信号词：问句短且含指代词才按指代式处理；长问句通常自包含。
_ANAPHORA = re.compile(r'这个|那个|这件|那件|这款|那款|这台|那台|它|刚才|上面|前面|刚说的|说过的')
_MAX_QUESTION_CHARS = 60


def looks_anaphoric(question):
    """判定问句是否为指代式短问句（纯词法，零误报优先于覆盖率）。"""
    text = (question or '').strip()
    return bool(text) and len(text) <= _MAX_QUESTION_CHARS and bool(_ANAPHORA.search(text))


def anaphora_expand(question, mission=None, focus=None):
    """指代式短问句 → 追加任务槽指代对象；其余情况原样返回（含回落）。

    补全词来源按优先级：mission.comparison_targets > mission.required_terms >
    mission.query。PRODUCT 焦点不额外处理——焦点语料已由服务端钉扎
    （compile_search_filter），这里只补词法上下文。
    """
    text = (question or '').strip()
    if not looks_anaphoric(text):
        return text
    mission = mission or {}
    terms = []
    for source in (mission.get('comparison_targets') or [], mission.get('required_terms') or []):
        for term in source:
            term = str(term).strip()
            if term and term not in terms:
                terms.append(term)
    if not terms:
        query = str(mission.get('query') or '').strip()
        if query:
            terms = [query[:40]]
    if not terms:
        return text
    return text + '（指代对象：' + '、'.join(terms[:3]) + '）'
