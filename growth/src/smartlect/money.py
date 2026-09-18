"""Exact Java decimal amounts as integer cents; floats and partial cents rejected."""
from decimal import Decimal, InvalidOperation


def to_cents(amount: str | Decimal) -> int:
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
