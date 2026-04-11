"""Tender analysis via Gemma4/Ollama — classifies, estimates, recommends."""

import json
import logging

from ..ai.ollama_client import generate as ollama_generate
from .models import Tender, COMPANIES, estimate_cost, recommend_company, PROJECT_TEMPLATES

logger = logging.getLogger("tenders.analyzer")


async def analyze_tender(tender: Tender) -> Tender:
    """Use Gemma4 to analyze a tender and fill in recommendations.

    Fills: recommended_company, complexity, estimated_cost, team_composition,
           risk_factors, tech_stack_required, documents_needed, technology
    """
    company_key = recommend_company(tender.country)
    company = COMPANIES[company_key]
    tender.recommended_company = company_key

    # Build analysis prompt
    prompt = f"""Analyze this government tender and provide a structured assessment.

TENDER:
- Title: {tender.title}
- Organization: {tender.organization}
- Country: {tender.country}
- Description: {tender.description[:800]}
- Amount: {tender.amount or 'Not specified'}
- Deadline: {tender.deadline or 'Not specified'}
- Category: {tender.category}

BIDDING COMPANY: {company['name']} ({company['country']})
Certifications: {', '.join(company['certifications']) if company['certifications'] else 'None'}

Respond in EXACTLY this JSON format (no markdown, no extra text):
{{
    "project_type": "web_portal|mobile_app|erp_system|cloud_migration|ai_ml_solution|cybersecurity_audit|hosting_infrastructure|general_it",
    "technology": "comma-separated tech stack required (e.g., Java, React, PostgreSQL, AWS)",
    "complexity": "low|medium|high",
    "duration_months": 3,
    "risk_factors": ["risk 1", "risk 2"],
    "tech_stack": ["tech1", "tech2"],
    "key_requirements": "brief summary of what needs to be built",
    "recommended_approach": "brief technical approach in 2-3 sentences"
}}
"""

    try:
        response = await ollama_generate(
            prompt=prompt,
            system_prompt="You are an expert IT project estimator. Analyze government tenders and provide structured assessments. Always respond in valid JSON.",
            temperature=0.3,
            max_tokens=800,
        )

        # Parse JSON from response
        response = response.strip()
        # Try to extract JSON if wrapped in markdown
        if "```" in response:
            import re
            json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                response = json_match.group(1)

        analysis = json.loads(response)

        # Fill tender with analysis
        tender.technology = analysis.get("technology", "General IT")
        tender.complexity = analysis.get("complexity", "medium")
        tender.tech_stack_required = analysis.get("tech_stack", [])
        tender.risk_factors = analysis.get("risk_factors", [])

        # Estimate cost
        project_type = analysis.get("project_type", "general_it")
        duration = analysis.get("duration_months", 4)
        region_map = {"ct_india": "india", "ct_us": "us", "logic_lane_sg": "singapore"}
        region = region_map.get(company_key, "india")

        cost_estimate = estimate_cost(project_type, region, duration)
        tender.estimated_cost = f"{cost_estimate['currency']} {cost_estimate['total']:,.0f}"
        tender.estimated_timeline = f"{cost_estimate['duration_months']} months"
        tender.team_composition = cost_estimate["breakdown"]

        # Documents needed
        if company_key == "ct_india":
            tender.documents_needed = [
                "Company Registration Certificate",
                "GST Certificate (27AAHCC9556B1ZF)",
                "PAN Card (AAHCC9556B)",
                "MSME Certificate",
                "Startup India / DIPP Certificate",
                "CMMI Level 3 Certificate",
                "ISO 9001:2015 Certificate",
                "ISO 27001:2015 Certificate",
                "Past Work Orders / Experience Certificates",
                "Financial Statements (Last 3 Years)",
                "EMD (Bank Guarantee / DD as required)",
                "Technical Bid Document",
                "Financial Bid Document",
                "Authorized Signatory Letter",
            ]
        elif company_key == "ct_us":
            tender.documents_needed = [
                "Certificate of Incorporation",
                "EIN / Tax ID",
                "SAM.gov Registration (CAGE Code)",
                "Past Performance References",
                "Technical Proposal",
                "Cost Proposal",
            ]
        else:  # logic_lane_sg
            tender.documents_needed = [
                "ACRA Business Profile",
                "UEN Number",
                "GeBIZ Vendor Registration",
                "Technical Proposal",
                "Cost Proposal",
            ]

        # Store raw analysis
        tender.raw_data["analysis"] = analysis
        tender.raw_data["cost_estimate"] = cost_estimate

        logger.info("Analyzed tender: %s → %s (%s, %s)",
                     tender.title[:50], company["short"],
                     tender.complexity, tender.estimated_cost)

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse AI analysis: %s", e)
        # Fallback
        tender.complexity = "medium"
        tender.technology = "General IT"
        region_map = {"ct_india": "india", "ct_us": "us", "logic_lane_sg": "singapore"}
        cost = estimate_cost("general_it", region_map.get(company_key, "india"))
        tender.estimated_cost = f"{cost['currency']} {cost['total']:,.0f}"
        tender.estimated_timeline = f"{cost['duration_months']} months"
        tender.team_composition = cost["breakdown"]

    except Exception as e:
        logger.error("Tender analysis failed: %s", e)

    return tender


async def search_contacts(tender: Tender) -> Tender:
    """Try to find contact information using SearXNG."""
    if tender.contact_email:
        return tender  # Already have contact

    try:
        from ..utils.search import search_web
        query = f"{tender.organization} procurement contact email {tender.country}"
        results = await search_web(query, max_results=3)

        for r in results:
            snippet = r.get("content", "") + r.get("title", "")
            # Look for email
            import re
            email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', snippet)
            if email_match:
                tender.contact_email = email_match.group(0)
                break
            # Look for phone
            phone_match = re.search(r'[\+\d][\d\s\-().]{8,}', snippet)
            if phone_match and not tender.contact_phone:
                tender.contact_phone = phone_match.group(0).strip()

    except Exception as e:
        logger.debug("Contact search failed: %s", e)

    return tender
