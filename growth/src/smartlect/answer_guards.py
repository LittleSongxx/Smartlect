"""确定性答案守卫：状态声明必须有本轮工具回执。

模型会在政策答复里夹带「查询到您的订单列表为空」式声明——听起来像查过，
实际本轮从没调用过任何订单工具（纯能力幻觉）。提示词压不住这类句式，
这里是机械闸门：答案命中状态声明句式、且本轮没有能产生该状态的工具回执，
即拒绝进入编译，走一轮修复重写。

句式清单刻意收窄：只收「断言观察结果」的复合句式（列表为空/暂无/查询到您…），
不收「查询本人订单需要登录」这类政策陈述——权限说明是合法答案内容。
"""
import unicodedata


def _fold(text):
    return unicodedata.normalize('NFKC', str(text or ''))


# 能产生用户订单/退款/支付状态观测的工具；答案声明这些状态时，本轮必须有其回执。
STATE_CLAIM_TOOLS = frozenset({
    'get_my_orders', 'get_order_status', 'get_refund_status', 'get_payment_status'})

# 断言用户订单/优惠券/账户当前状态的句式（复合短语，避免误伤政策陈述）。
_STATE_CLAIM_PATTERNS = (
    '订单列表为空', '暂无订单', '订单记录为空', '无订单记录',
    '查询到您的订单', '查到您的订单', '查询到您账户', '查到您账户', '查询到您的账户',
    '查询到您的优惠券', '查到您的优惠券', '优惠券列表为空', '暂无可用优惠券', '暂无优惠券',
    '没有未使用的优惠券', '无未使用的优惠券', '账户下暂无', '名下暂无',
)


def unsupported_state_claims(answer, accepted_tools):
    """答案中命中状态声明句式、而本轮 accepted_tools 没有任何状态观测工具时，
    返回命中的句式列表（空列表=通过）。"""
    claims = []
    if not (STATE_CLAIM_TOOLS & set(accepted_tools or [])):
        text = _fold(answer)
        claims += [pattern for pattern in _STATE_CLAIM_PATTERNS if pattern in text]
    # 积分余额：没有任何积分观测工具，任何「您有/您的/当前」式余额声明都是编造
    for sentence in _fold(answer).replace('\n', '。').split('。'):
        if '积分' in sentence and any(flag in sentence for flag in ('您有', '您当前', '您的积分', '积分余额')):
            claims.append('积分余额声明:' + sentence.strip()[:40])
    return claims
