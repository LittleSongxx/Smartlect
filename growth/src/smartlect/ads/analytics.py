"""Adapted from frozen advertising analytics; money is integer cents.

Historical ROAS is a rule baseline signal, not a marginal-return prediction.
These functions propose values only; they neither spend money nor mutate ads.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import ceil, floor

LOW_CTR_PER_MILLE = 5


def _nonnegative_int(value: int, name: str):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def to_cents(amount: str | Decimal) -> int:
    """Convert an exact Java decimal amount, rejecting floats and partial cents."""
    if not isinstance(amount, (str, Decimal)):
        raise ValueError("amount must be a decimal string or Decimal")
    try:
        decimal_amount = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError("amount must be a valid decimal") from exc
    if not decimal_amount.is_finite() or decimal_amount < 0:
        raise ValueError("amount must be finite, nonnegative and in whole cents")
    numerator, denominator = decimal_amount.as_integer_ratio()
    cents, remainder = divmod(numerator * 100, denominator)
    if remainder:
        raise ValueError("amount must be in whole cents")
    return cents


@dataclass(frozen=True)
class CampaignMetrics:
    campaign_id: str
    budget_cents: int
    spent_cents: int = 0
    paid_cents: int = 0
    refunded_cents: int = 0
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0  # Distinct attributed payment orders, supplied by the ledger.
    stock: int = 0

    def __post_init__(self):
        if not self.campaign_id:
            raise ValueError("campaign_id is required")
        for name, value in vars(self).items():
            if name != "campaign_id":
                _nonnegative_int(value, name)
        if self.spent_cents > self.budget_cents:
            raise ValueError("spent_cents cannot exceed configured budget_cents")

    @property
    def remaining_cents(self):
        return self.budget_cents - self.spent_cents

    @property
    def ctr(self):
        return self.clicks / self.impressions if self.impressions else None

    @property
    def cvr(self):
        return self.conversions / self.clicks if self.clicks else None

    @property
    def cpo_cents(self):
        return self.spent_cents / self.conversions if self.conversions else None

    @property
    def roas(self):
        return ((self.paid_cents - self.refunded_cents) / self.spent_cents
                if self.spent_cents else None)


@dataclass(frozen=True)
class BudgetAllocation:
    campaign_id: str
    current_budget_cents: int
    recommended_budget_cents: int
    reason_code: str


def optimize_budget_allocation(
    metrics_list: list[CampaignMetrics],
    total_budget_cents: int | None = None,
    max_change_pct: Decimal = Decimal("0.5"),
) -> list[BudgetAllocation]:
    """Allocate within total and per-campaign caps; unallocated budget is allowed.

    Configured budget and spent amounts are separate. A stockout removes future
    spend before any score comparison. Infeasible minimum bounds raise instead
    of silently breaking constraints, and no renormalization can break a cap.
    """
    if not isinstance(max_change_pct, Decimal) or not max_change_pct.is_finite() or not 0 <= max_change_pct <= 1:
        raise ValueError("max_change_pct must be a Decimal between 0 and 1")
    if len({m.campaign_id for m in metrics_list}) != len(metrics_list):
        raise ValueError("campaign_id values must be unique")
    total = (sum(m.budget_cents for m in metrics_list)
             if total_budget_cents is None else total_budget_cents)
    _nonnegative_int(total, "total_budget_cents")
    change = Fraction(max_change_pct)
    lower = [max(m.spent_cents, ceil(m.budget_cents * (1 - change)))
             if m.stock else m.spent_cents for m in metrics_list]
    upper = [floor(m.budget_cents * (1 + change))
             if m.stock else m.spent_cents for m in metrics_list]
    if sum(lower) > total:
        raise ValueError("total budget cannot satisfy spent amounts and minimum change bounds")
    result = lower.copy()
    remaining = total - sum(result)
    order = sorted(range(len(metrics_list)), key=lambda i: (
        -Fraction(max(0, metrics_list[i].paid_cents - metrics_list[i].refunded_cents),
                  max(1, metrics_list[i].spent_cents)), metrics_list[i].campaign_id))
    for index in order:
        extra = min(remaining, upper[index] - result[index])
        result[index] += extra
        remaining -= extra
    return [BudgetAllocation(m.campaign_id, m.budget_cents, result[i],
                             "stockout_pause" if not m.stock else "historical_roas_baseline")
            for i, m in enumerate(metrics_list)]


def detect_anomalies(metrics_list: list[CampaignMetrics], ctr_threshold=LOW_CTR_PER_MILLE / 1000,
                     cpo_ceiling_cents=20000, roas_floor=1.0) -> list[dict]:
    """Preserve the source's minimum-sample checks with explicit absent ratios."""
    alerts = []
    for m in metrics_list:
        checks = (
            (m.impressions > 100 and m.ctr is not None and m.ctr < ctr_threshold, "low_ctr", m.ctr),
            (m.cpo_cents is not None and m.cpo_cents > cpo_ceiling_cents, "high_cpo", m.cpo_cents),
            (m.spent_cents > 10000 and m.roas is not None and m.roas < roas_floor, "low_roas", m.roas),
        )
        for triggered, reason, value in checks:
            if triggered:
                alerts.append({"campaign_id": m.campaign_id, "reason_code": reason, "value": value})
    return alerts
