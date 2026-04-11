"""Tender data models and cost database."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Tender:
    """Represents a government/private tender."""
    title: str
    organization: str
    country: str
    source: str  # sam_gov, cppp, gem, uk_contracts, etc.
    source_url: str

    # Details
    description: str = ""
    technology: str = ""  # tech category detected
    amount: str = ""  # tender value
    currency: str = ""
    emd: str = ""  # earnest money deposit
    deadline: str = ""  # last date to apply
    published_date: str = ""
    reference_number: str = ""
    category: str = ""  # IT, software, hosting, etc.

    # Contact
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    contact_address: str = ""

    # Analysis (filled by Gemma4)
    recommended_company: str = ""  # ct_india, ct_us, logic_lane_sg
    complexity: str = ""  # low, medium, high
    estimated_cost: str = ""
    estimated_timeline: str = ""
    team_composition: list[dict] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    tech_stack_required: list[str] = field(default_factory=list)
    documents_needed: list[str] = field(default_factory=list)

    # Meta
    raw_data: dict = field(default_factory=dict)
    crawled_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ── Company Profiles ──

COMPANIES = {
    "ct_india": {
        "name": "Chandorkar Technologies OPC Pvt Ltd",
        "short": "CT India",
        "country": "India",
        "address": "Pune, Maharashtra, India",
        "gst": "27AAHCC9556B1ZF",
        "pan": "AAHCC9556B",
        "certifications": [
            "CMMI Level 3",
            "ISO 9001:2015",
            "ISO 27001:2015",
            "Startup India Registered",
            "DIPP Registered",
            "MSME Registered",
        ],
        "revenue_last_fy": "INR 2.10 Crore",
        "currencies": ["INR", "USD"],
        "target_countries": ["India"],
    },
    "ct_us": {
        "name": "Chandorkar Technologies Inc",
        "short": "CT US",
        "country": "USA",
        "address": "United States",
        "certifications": [],
        "revenue_last_fy": "New Entity",
        "currencies": ["USD"],
        "target_countries": ["USA", "Global", "Canada"],
    },
    "logic_lane_sg": {
        "name": "Logic Lane Pte Ltd",
        "short": "Logic Lane SG",
        "country": "Singapore",
        "address": "Singapore",
        "certifications": [],
        "revenue_last_fy": "New Entity",
        "currencies": ["SGD", "USD"],
        "target_countries": ["Singapore", "APAC", "Global"],
    },
}


# ── Cost Database ──

COST_DB = {
    "india": {
        "currency": "INR",
        "monthly_rates": {
            "Project Manager": 150000,
            "Senior Developer": 120000,
            "Mid Developer": 80000,
            "Junior Developer": 45000,
            "QA Engineer": 60000,
            "DevOps Engineer": 100000,
            "UI/UX Designer": 80000,
            "Business Analyst": 90000,
            "Solution Architect": 180000,
            "Database Administrator": 100000,
            "Security Specialist": 130000,
        },
        "overhead_multiplier": 1.3,  # 30% overhead (office, infra, etc.)
        "profit_margin": 0.20,  # 20% profit margin
    },
    "us": {
        "currency": "USD",
        "monthly_rates": {
            "Project Manager": 12000,
            "Senior Developer": 15000,
            "Mid Developer": 10000,
            "Junior Developer": 6000,
            "QA Engineer": 8000,
            "DevOps Engineer": 13000,
            "UI/UX Designer": 10000,
            "Business Analyst": 11000,
            "Solution Architect": 18000,
            "Database Administrator": 12000,
            "Security Specialist": 14000,
        },
        "overhead_multiplier": 1.4,
        "profit_margin": 0.25,
    },
    "singapore": {
        "currency": "SGD",
        "monthly_rates": {
            "Project Manager": 10000,
            "Senior Developer": 12000,
            "Mid Developer": 8000,
            "Junior Developer": 5000,
            "QA Engineer": 6500,
            "DevOps Engineer": 11000,
            "UI/UX Designer": 8000,
            "Business Analyst": 9000,
            "Solution Architect": 15000,
            "Database Administrator": 10000,
            "Security Specialist": 12000,
        },
        "overhead_multiplier": 1.35,
        "profit_margin": 0.22,
    },
}


# ── Project Type Templates ──

PROJECT_TEMPLATES = {
    "web_portal": {
        "name": "Web Portal Development",
        "typical_team": [
            {"role": "Project Manager", "months": 1.0, "count": 1},
            {"role": "Solution Architect", "months": 0.5, "count": 1},
            {"role": "Senior Developer", "months": 1.0, "count": 1},
            {"role": "Mid Developer", "months": 1.0, "count": 2},
            {"role": "UI/UX Designer", "months": 0.5, "count": 1},
            {"role": "QA Engineer", "months": 0.5, "count": 1},
            {"role": "DevOps Engineer", "months": 0.3, "count": 1},
        ],
        "duration_months": 3,
    },
    "mobile_app": {
        "name": "Mobile Application Development",
        "typical_team": [
            {"role": "Project Manager", "months": 1.0, "count": 1},
            {"role": "Senior Developer", "months": 1.0, "count": 2},
            {"role": "Mid Developer", "months": 1.0, "count": 2},
            {"role": "UI/UX Designer", "months": 0.5, "count": 1},
            {"role": "QA Engineer", "months": 0.7, "count": 1},
        ],
        "duration_months": 4,
    },
    "erp_system": {
        "name": "ERP System Implementation",
        "typical_team": [
            {"role": "Project Manager", "months": 1.0, "count": 1},
            {"role": "Solution Architect", "months": 1.0, "count": 1},
            {"role": "Senior Developer", "months": 1.0, "count": 2},
            {"role": "Mid Developer", "months": 1.0, "count": 3},
            {"role": "Business Analyst", "months": 1.0, "count": 1},
            {"role": "Database Administrator", "months": 0.5, "count": 1},
            {"role": "QA Engineer", "months": 0.7, "count": 2},
            {"role": "DevOps Engineer", "months": 0.3, "count": 1},
        ],
        "duration_months": 8,
    },
    "cloud_migration": {
        "name": "Cloud Migration",
        "typical_team": [
            {"role": "Project Manager", "months": 1.0, "count": 1},
            {"role": "Solution Architect", "months": 0.7, "count": 1},
            {"role": "DevOps Engineer", "months": 1.0, "count": 2},
            {"role": "Senior Developer", "months": 0.5, "count": 1},
            {"role": "Security Specialist", "months": 0.3, "count": 1},
            {"role": "QA Engineer", "months": 0.5, "count": 1},
        ],
        "duration_months": 4,
    },
    "ai_ml_solution": {
        "name": "AI/ML Solution Development",
        "typical_team": [
            {"role": "Project Manager", "months": 1.0, "count": 1},
            {"role": "Solution Architect", "months": 0.5, "count": 1},
            {"role": "Senior Developer", "months": 1.0, "count": 2},
            {"role": "Mid Developer", "months": 1.0, "count": 1},
            {"role": "QA Engineer", "months": 0.5, "count": 1},
            {"role": "DevOps Engineer", "months": 0.5, "count": 1},
        ],
        "duration_months": 5,
    },
    "cybersecurity_audit": {
        "name": "Cybersecurity Audit & Implementation",
        "typical_team": [
            {"role": "Project Manager", "months": 1.0, "count": 1},
            {"role": "Security Specialist", "months": 1.0, "count": 2},
            {"role": "DevOps Engineer", "months": 0.5, "count": 1},
            {"role": "Senior Developer", "months": 0.3, "count": 1},
        ],
        "duration_months": 3,
    },
    "hosting_infrastructure": {
        "name": "Hosting & Infrastructure Setup",
        "typical_team": [
            {"role": "Project Manager", "months": 0.5, "count": 1},
            {"role": "DevOps Engineer", "months": 1.0, "count": 2},
            {"role": "Security Specialist", "months": 0.3, "count": 1},
        ],
        "duration_months": 2,
    },
    "general_it": {
        "name": "General IT Services",
        "typical_team": [
            {"role": "Project Manager", "months": 1.0, "count": 1},
            {"role": "Senior Developer", "months": 1.0, "count": 1},
            {"role": "Mid Developer", "months": 1.0, "count": 2},
            {"role": "QA Engineer", "months": 0.5, "count": 1},
        ],
        "duration_months": 4,
    },
}


def estimate_cost(project_type: str, region: str, duration_months: int | None = None) -> dict:
    """Estimate project cost based on type and region.

    Returns: {total, currency, breakdown: [{role, count, months, monthly_rate, subtotal}], duration}
    """
    template = PROJECT_TEMPLATES.get(project_type, PROJECT_TEMPLATES["general_it"])
    rates = COST_DB.get(region, COST_DB["india"])
    duration = duration_months or template["duration_months"]

    breakdown = []
    total_raw = 0

    for member in template["typical_team"]:
        role = member["role"]
        count = member["count"]
        months = member["months"] * duration
        monthly_rate = rates["monthly_rates"].get(role, 80000)
        subtotal = monthly_rate * count * months

        breakdown.append({
            "role": role,
            "count": count,
            "months": round(months, 1),
            "monthly_rate": monthly_rate,
            "subtotal": round(subtotal),
        })
        total_raw += subtotal

    total_with_overhead = total_raw * rates["overhead_multiplier"]
    total_with_profit = total_with_overhead * (1 + rates["profit_margin"])

    return {
        "project_type": template["name"],
        "region": region,
        "currency": rates["currency"],
        "duration_months": duration,
        "breakdown": breakdown,
        "subtotal": round(total_raw),
        "overhead": round(total_with_overhead - total_raw),
        "profit": round(total_with_profit - total_with_overhead),
        "total": round(total_with_profit),
    }


def recommend_company(country: str) -> str:
    """Recommend which company should bid based on tender country."""
    country_lower = country.lower().strip()

    india_keywords = ["india", "indian", "bharat", "delhi", "mumbai", "pune", "bangalore",
                      "hyderabad", "chennai", "kolkata", "state", "ministry"]
    us_keywords = ["usa", "united states", "us ", "america", "federal", "washington"]
    sg_keywords = ["singapore", "sg"]
    apac_keywords = ["asia", "apac", "asean", "japan", "korea", "australia", "new zealand"]

    if any(kw in country_lower for kw in india_keywords):
        return "ct_india"
    if any(kw in country_lower for kw in us_keywords):
        return "ct_us"
    if any(kw in country_lower for kw in sg_keywords):
        return "logic_lane_sg"
    if any(kw in country_lower for kw in apac_keywords):
        return "logic_lane_sg"

    # Default: US company for global tenders
    return "ct_us"
