"""Lead scoring algorithm with weighted multi-factor analysis."""

import json
from pathlib import Path

from ..db.repository import get_lead, get_scan_results, get_contacts, save_score


_WEIGHTS_PATH = Path(__file__).parent.parent.parent.parent / "data" / "scoring_weights.json"
_weights: dict | None = None


def _load_weights() -> dict:
    global _weights
    if _weights is None:
        try:
            _weights = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _weights = {
                "tech_opportunity": {
                    "max_score": 30,
                    "outdated_tech_per_item": 5,
                    "security_critical": 8,
                    "security_warning": 3,
                    "performance_critical": 6,
                    "performance_warning": 2,
                    "missing_feature_high": 4,
                    "missing_feature_medium": 2,
                },
                "budget_signal": {
                    "max_score": 25,
                    "has_explicit_budget": 10,
                    "budget_above_10k": 8,
                    "budget_above_50k": 15,
                    "large_company": 8,
                    "medium_company": 5,
                },
                "engagement_readiness": {
                    "max_score": 20,
                    "recent_project_posting": 8,
                    "actively_hiring": 6,
                    "recently_funded": 8,
                    "new_product_launch": 5,
                },
                "contact_quality": {
                    "max_score": 15,
                    "has_verified_email": 8,
                    "has_decision_maker": 7,
                    "has_any_email": 3,
                },
                "fit_score": {
                    "max_score": 10,
                    "needs_developer": 5,
                    "enterprise_project": 3,
                    "startup_building_mvp": 4,
                },
            }
    return _weights


async def score_lead(lead_id: str) -> dict:
    """Calculate and save a comprehensive lead score."""
    lead = await get_lead(lead_id)
    if not lead:
        return {"error": f"Lead {lead_id} not found"}

    scans = await get_scan_results(lead_id)
    contacts = await get_contacts(lead_id)
    weights = _load_weights()

    signals = json.loads(lead.get("signals", "[]")) if isinstance(lead.get("signals"), str) else (lead.get("signals") or [])
    raw = json.loads(lead.get("raw_data", "{}")) if isinstance(lead.get("raw_data"), str) else (lead.get("raw_data") or {})

    scores = {
        "tech": _calc_tech_score(scans, weights["tech_opportunity"]),
        "opportunity": _calc_engagement_score(signals, weights["engagement_readiness"]),
        "budget": _calc_budget_score(lead, signals, weights["budget_signal"]),
        "engagement": _calc_engagement_score(signals, weights["engagement_readiness"]),
        "contact": _calc_contact_score(contacts, weights["contact_quality"]),
    }

    result = await save_score(lead_id, scores)

    # Add qualitative assessment
    total = result["total_score"]
    if total >= 70:
        result["tier"] = "hot"
        result["recommendation"] = "High-priority lead — send personalized outreach immediately"
    elif total >= 40:
        result["tier"] = "warm"
        result["recommendation"] = "Good prospect — add to nurture campaign"
    else:
        result["tier"] = "cold"
        result["recommendation"] = "Low priority — monitor for future signals"

    return result


def _calc_tech_score(scans: list[dict], weights: dict) -> float:
    """Score based on technology issues found in website scans."""
    score = 0.0
    max_score = weights["max_score"]

    for scan in scans:
        result = scan.get("result", {})

        if scan["scan_type"] == "tech_stack":
            outdated = result.get("outdated", [])
            score += len(outdated) * weights["outdated_tech_per_item"]

        elif scan["scan_type"] == "security":
            issues = result.get("issues", [])
            for issue in issues:
                if issue.get("severity") == "critical":
                    score += weights["security_critical"]
                elif issue.get("severity") == "warning":
                    score += weights["security_warning"]

        elif scan["scan_type"] == "performance":
            issues = result.get("issues", [])
            for issue in issues:
                if issue.get("severity") == "critical":
                    score += weights["performance_critical"]
                elif issue.get("severity") == "warning":
                    score += weights["performance_warning"]

        elif scan["scan_type"] == "features":
            missing = result.get("missing_features", [])
            for feat in missing:
                if feat.get("impact") == "high":
                    score += weights["missing_feature_high"]
                elif feat.get("impact") == "medium":
                    score += weights["missing_feature_medium"]

    return min(score, max_score)


def _calc_budget_score(lead: dict, signals: list[str], weights: dict) -> float:
    """Score based on budget signals."""
    score = 0.0
    max_score = weights["max_score"]

    budget = lead.get("budget_estimate")
    if budget:
        score += weights["has_explicit_budget"]
        if budget >= 50000:
            score += weights["budget_above_50k"]
        elif budget >= 10000:
            score += weights["budget_above_10k"]

    if "high_spending_client" in signals:
        score += 5
    if "enterprise_project" in signals:
        score += 5

    return min(score, max_score)


def _calc_engagement_score(signals: list[str], weights: dict) -> float:
    """Score based on engagement readiness signals."""
    score = 0.0
    max_score = weights["max_score"]

    signal_scores = {
        "upwork_project": weights["recent_project_posting"],
        "clutch_listed": 3,
        "actively_hiring": weights["actively_hiring"],
        "hiring_engineers": weights["actively_hiring"],
        "recently_funded": weights["recently_funded"],
        "funded_startup": weights["recently_funded"],
        "new_product": weights["new_product_launch"],
        "producthunt_launch": weights["new_product_launch"],
        "needs_developer": 6,
        "needs_technical_cofounder": 8,
        "building_mvp": 5,
        "high_budget_project": 5,
    }

    for signal in signals:
        if signal in signal_scores:
            score += signal_scores[signal]

    return min(score, max_score)


def _calc_contact_score(contacts: list[dict], weights: dict) -> float:
    """Score based on contact quality."""
    score = 0.0
    max_score = weights["max_score"]

    if contacts:
        score += weights["has_any_email"]

        has_verified = any(c.get("email_verified") for c in contacts)
        if has_verified:
            score += weights["has_verified_email"]

        has_dm = any(c.get("title") and any(
            t in c["title"].lower()
            for t in ["ceo", "cto", "founder", "director", "vp", "head"]
        ) for c in contacts)
        if has_dm:
            score += weights["has_decision_maker"]

    return min(score, max_score)
