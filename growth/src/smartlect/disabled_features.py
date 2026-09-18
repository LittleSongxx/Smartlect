"""Retired product surfaces. Library code stays; HTTP entry refuses after auth."""

CODES = {
    "merchant_planner": "merchant_planner_disabled",
    "review_analysis": "review_analysis_disabled",
    "growth_report": "growth_report_disabled",
    "ads": "ads_disabled",
}
STATUS = 410


def reject(feature):
    from smartlect.state import StateError
    raise StateError(CODES[feature], STATUS)
