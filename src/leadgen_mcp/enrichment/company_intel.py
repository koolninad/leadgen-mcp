"""Company intelligence gathering: size, revenue, industry estimates."""

import re

from bs4 import BeautifulSoup

from ..utils.http import create_client


async def get_company_intel(domain: str) -> dict:
    """Gather company intelligence from their website and public sources."""
    intel = {
        "domain": domain,
        "company_name": None,
        "description": None,
        "employee_estimate": None,
        "revenue_estimate": None,
        "industry": None,
        "founded_year": None,
        "social_links": {},
        "technologies_mentioned": [],
        "hiring_signals": [],
    }

    # Scrape main website
    async with create_client(timeout=15.0) as client:
        # Check homepage
        try:
            resp = await client.get(f"https://{domain}")
            if resp.status_code == 200:
                _parse_homepage(resp.text, intel)
        except Exception:
            pass

        # Check about page
        for about_path in ["/about", "/about-us", "/company"]:
            try:
                resp = await client.get(f"https://{domain}{about_path}")
                if resp.status_code == 200:
                    _parse_about_page(resp.text, intel)
                    break
            except Exception:
                continue

        # Check careers page for hiring signals
        for careers_path in ["/careers", "/jobs", "/join-us", "/work-with-us"]:
            try:
                resp = await client.get(f"https://{domain}{careers_path}")
                if resp.status_code == 200:
                    _parse_careers_page(resp.text, intel)
                    break
            except Exception:
                continue

    # Estimate revenue from employee count
    if intel["employee_estimate"]:
        intel["revenue_estimate"] = _estimate_revenue(intel["employee_estimate"])

    return intel


def _parse_homepage(html: str, intel: dict):
    """Extract company info from homepage."""
    soup = BeautifulSoup(html, "lxml")

    # Company name from title
    title = soup.find("title")
    if title:
        name = title.get_text(strip=True)
        name = re.sub(r"\s*[\|–\-:].+$", "", name)
        intel["company_name"] = name

    # Meta description
    desc = soup.find("meta", {"name": "description"})
    if desc and desc.get("content"):
        intel["description"] = desc["content"]

    # Social links
    social_patterns = {
        "linkedin": r"linkedin\.com",
        "twitter": r"(?:twitter|x)\.com",
        "facebook": r"facebook\.com",
        "github": r"github\.com",
        "instagram": r"instagram\.com",
        "youtube": r"youtube\.com",
    }

    for link in soup.find_all("a", href=True):
        href = link["href"]
        for platform, pattern in social_patterns.items():
            if re.search(pattern, href, re.I) and platform not in intel["social_links"]:
                intel["social_links"][platform] = href

    # Structured data
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            import json
            data = json.loads(script.string)
            if isinstance(data, dict):
                if data.get("@type") == "Organization":
                    intel["company_name"] = intel["company_name"] or data.get("name")
                    intel["description"] = intel["description"] or data.get("description")
                    if data.get("numberOfEmployees"):
                        emp = data["numberOfEmployees"]
                        if isinstance(emp, dict):
                            intel["employee_estimate"] = emp.get("value")
                    if data.get("foundingDate"):
                        year_match = re.search(r"(\d{4})", str(data["foundingDate"]))
                        if year_match:
                            intel["founded_year"] = int(year_match.group(1))
        except Exception:
            continue


def _parse_about_page(html: str, intel: dict):
    """Extract company info from about page."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text()

    # Employee count patterns
    emp_patterns = [
        r"(\d{1,3}(?:,\d{3})*)\+?\s*(?:employees|team members|people|staff)",
        r"team\s+of\s+(\d{1,3}(?:,\d{3})*)\+?",
        r"(\d{1,3}(?:,\d{3})*)\+?\s*(?:strong|professionals|experts)",
    ]
    for pattern in emp_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            intel["employee_estimate"] = int(match.group(1).replace(",", ""))
            break

    # Founded year
    year_match = re.search(r"(?:founded|established|since|started)\s+(?:in\s+)?(\d{4})", text, re.I)
    if year_match:
        year = int(year_match.group(1))
        if 1900 < year < 2030:
            intel["founded_year"] = year

    # Industry keywords
    industry_keywords = {
        "healthcare": ["health", "medical", "pharma", "biotech", "clinical"],
        "fintech": ["financial", "fintech", "banking", "payment", "insurance"],
        "ecommerce": ["ecommerce", "e-commerce", "retail", "shopping", "marketplace"],
        "education": ["education", "edtech", "learning", "school", "university"],
        "saas": ["saas", "software as a service", "cloud platform", "subscription"],
        "real_estate": ["real estate", "property", "realty"],
        "logistics": ["logistics", "supply chain", "shipping", "freight"],
        "media": ["media", "publishing", "content", "news"],
    }

    text_lower = text.lower()
    for industry, keywords in industry_keywords.items():
        for kw in keywords:
            if kw in text_lower:
                intel["industry"] = industry
                return


def _parse_careers_page(html: str, intel: dict):
    """Extract hiring signals from careers page."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text().lower()

    hiring_signals = []
    if re.search(r"engineer|developer|programmer", text):
        hiring_signals.append("hiring_engineers")
    if re.search(r"senior|lead|principal|staff", text):
        hiring_signals.append("hiring_senior_roles")
    if re.search(r"remote|hybrid|work from", text):
        hiring_signals.append("remote_friendly")
    if re.search(r"series [a-d]|funding|backed by|raised", text):
        hiring_signals.append("recently_funded")

    # Count open positions
    job_listings = soup.select(".job-listing, .position, [class*='job'], [class*='opening']")
    if job_listings:
        hiring_signals.append(f"open_positions_{len(job_listings)}")

    intel["hiring_signals"] = hiring_signals


def _estimate_revenue(employee_count: int) -> str:
    """Rough revenue estimate based on employee count (B2B software avg ~$200K/employee)."""
    revenue = employee_count * 200_000
    if revenue >= 1_000_000_000:
        return f"${revenue / 1_000_000_000:.1f}B+"
    elif revenue >= 1_000_000:
        return f"${revenue / 1_000_000:.0f}M+"
    elif revenue >= 1_000:
        return f"${revenue / 1_000:.0f}K+"
    return f"${revenue}"
