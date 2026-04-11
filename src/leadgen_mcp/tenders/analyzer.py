"""Tender deep analysis via Gemma4/Ollama + SearXNG research.

Does real research on the organization, understands the tender deeply,
and generates submission-ready proposal content.
"""

import json
import logging
import re

from ..ai.ollama_client import generate as ollama_generate
from .models import Tender, COMPANIES, estimate_cost, recommend_company, PROJECT_TEMPLATES

logger = logging.getLogger("tenders.analyzer")


async def _search_web(query: str, max_results: int = 5) -> list[dict]:
    """Search via SearXNG for context."""
    try:
        from ..utils.search import search_web
        return await search_web(query, max_results=max_results)
    except Exception as e:
        logger.debug("Web search failed: %s", e)
        return []


async def _ask_gemma(prompt: str, system: str = "", temperature: float = 0.4, max_tokens: int = 2000) -> str:
    """Query Gemma4 with thinking mode."""
    try:
        return await ollama_generate(
            prompt=prompt,
            system_prompt=system or "You are a senior IT consultant writing government tender proposals. Be specific, detailed, and professional. No fluff.",
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.error("Gemma4 failed: %s", e)
        return ""


async def research_organization(tender: Tender) -> dict:
    """Research the tendering organization via web search."""
    org_info = {"about": "", "recent_projects": "", "tech_context": ""}

    # Search for organization info
    results = await _search_web(f"{tender.organization} {tender.country} about")
    if results:
        snippets = " ".join(r.get("content", "")[:200] for r in results[:3])
        org_info["about"] = snippets[:500]

    # Search for their tech landscape
    results = await _search_web(f"{tender.organization} IT infrastructure technology digital")
    if results:
        snippets = " ".join(r.get("content", "")[:200] for r in results[:3])
        org_info["tech_context"] = snippets[:500]

    # Search for similar past projects
    results = await _search_web(f"{tender.organization} software project tender awarded")
    if results:
        snippets = " ".join(r.get("content", "")[:200] for r in results[:3])
        org_info["recent_projects"] = snippets[:500]

    return org_info


async def analyze_tender(tender: Tender) -> Tender:
    """Deep analysis of a tender — research + AI analysis + cost estimation."""

    # Step 1: Determine recommended company
    company_key = recommend_company(tender.country)
    company = COMPANIES[company_key]
    tender.recommended_company = company_key

    # Step 2: Research the organization
    logger.info("  Researching %s...", tender.organization)
    org_research = await research_organization(tender)

    # Step 3: Deep AI analysis
    logger.info("  AI analysis...")
    analysis_prompt = f"""Analyze this government IT tender in depth.

TENDER DETAILS:
- Title: {tender.title}
- Organization: {tender.organization}
- Country: {tender.country}
- Description: {tender.description[:1000]}
- Amount: {tender.amount or 'Not specified'}
- Deadline: {tender.deadline or 'Not specified'}

RESEARCH ON ORGANIZATION:
{org_research.get('about', 'No information found')[:400]}

TECH CONTEXT:
{org_research.get('tech_context', '')[:400]}

Respond in this EXACT JSON format (no markdown, no extra text):
{{
    "project_type": "web_portal|mobile_app|erp_system|cloud_migration|ai_ml_solution|cybersecurity_audit|hosting_infrastructure|general_it",
    "technology": "specific tech stack required",
    "complexity": "low|medium|high",
    "duration_months": 4,
    "risk_factors": ["specific risk 1 with mitigation", "specific risk 2 with mitigation", "specific risk 3 with mitigation"],
    "tech_stack": ["tech1", "tech2", "tech3"],
    "key_requirements": "detailed summary of what needs to be built (3-4 sentences)",
    "client_pain_points": "what problems the client is trying to solve (2-3 sentences)",
    "recommended_approach": "detailed technical approach (4-5 sentences)",
    "scope_of_work": ["Phase 1: Discovery & Requirements (list specific tasks)", "Phase 2: Design (list specifics)", "Phase 3: Development (specifics)", "Phase 4: Testing (specifics)", "Phase 5: Deployment & Training"],
    "sla_terms": "recommended SLA — uptime %, response times, support hours",
    "security_approach": "how to handle data security and compliance",
    "pricing_model": "fixed|time_and_materials|milestone_based",
    "assumptions": ["assumption 1", "assumption 2", "assumption 3"]
}}
"""

    try:
        response = await _ask_gemma(analysis_prompt, max_tokens=2500)
        response = response.strip()

        # Extract JSON
        if "```" in response:
            json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                response = json_match.group(1)

        # Try to find JSON object
        brace_start = response.find("{")
        brace_end = response.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            response = response[brace_start:brace_end]

        analysis = json.loads(response)

    except (json.JSONDecodeError, Exception) as e:
        logger.warning("AI analysis parse failed: %s. Using defaults.", e)
        analysis = {
            "project_type": "general_it",
            "technology": "To be determined",
            "complexity": "medium",
            "duration_months": 4,
            "risk_factors": [
                "Scope changes — mitigated by formal change control process",
                "Resource availability — mitigated by dedicated team allocation",
                "Integration complexity — mitigated by phased integration approach",
            ],
            "tech_stack": [],
            "key_requirements": tender.description[:200],
            "client_pain_points": f"{tender.organization} needs IT solutions for operational efficiency.",
            "recommended_approach": "Agile methodology with iterative development.",
            "scope_of_work": [
                "Phase 1: Requirements Gathering & Analysis",
                "Phase 2: System Design & Architecture",
                "Phase 3: Development & Integration",
                "Phase 4: Testing & QA",
                "Phase 5: Deployment, Training & Handover",
            ],
            "sla_terms": "99.5% uptime, 4-hour response for critical issues, 8x5 support",
            "security_approach": "ISO 27001 compliant data handling, encryption at rest and in transit",
            "pricing_model": "milestone_based",
            "assumptions": [
                "Client will provide timely access to stakeholders",
                "Infrastructure/hosting costs are separate",
                "Third-party license costs are not included",
            ],
        }

    # Step 4: Generate executive summary via AI
    logger.info("  Generating executive summary...")
    exec_summary = await _ask_gemma(
        f"""Write a compelling 2-paragraph executive summary for a tender proposal.

Tender: {tender.title}
Client: {tender.organization}
Our Company: {company['name']} ({', '.join(company.get('certifications', [])[:3])})
Client's Pain Points: {analysis.get('client_pain_points', '')}
Our Approach: {analysis.get('recommended_approach', '')}
Tech Stack: {analysis.get('technology', '')}

Write 2 paragraphs:
1. The problem and our understanding of it
2. Why we are the best fit (mention specific certifications and experience)

Be specific and confident. No generic statements.""",
        max_tokens=500,
    )

    # Step 5: Generate technical approach detail
    logger.info("  Generating technical approach...")
    tech_approach = await _ask_gemma(
        f"""Write a detailed technical approach for this project.

Project: {tender.title}
Tech Stack: {analysis.get('technology', '')}
Requirements: {analysis.get('key_requirements', '')}
Methodology: Agile/Scrum

Write 5 paragraphs covering:
1. Overall Architecture (microservices/monolith, cloud provider, database choice)
2. Development Methodology (sprint structure, CI/CD, code review process)
3. Integration Strategy (APIs, third-party systems, data migration)
4. Quality Assurance (testing types, automation, performance benchmarks)
5. Security & Compliance (encryption, access control, audit logging)

Be technically specific. Mention actual technologies and tools.""",
        max_tokens=1500,
    )

    # Step 6: Cost estimation
    project_type = analysis.get("project_type", "general_it")
    duration = analysis.get("duration_months", 4)
    region_map = {"ct_india": "india", "ct_us": "us", "logic_lane_sg": "singapore"}
    region = region_map.get(company_key, "india")
    cost_estimate = estimate_cost(project_type, region, duration)

    # Fill tender object
    tender.technology = analysis.get("technology", "General IT")
    tender.complexity = analysis.get("complexity", "medium")
    tender.tech_stack_required = analysis.get("tech_stack", [])
    tender.risk_factors = analysis.get("risk_factors", [])
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
            "Audited Financial Statements (Last 3 Years)",
            "EMD (Bank Guarantee / DD as required)",
            "Technical Bid Document (Signed & Sealed)",
            "Financial Bid Document (Signed & Sealed)",
            "Authorized Signatory Letter / Board Resolution",
            "Self-Declaration of No Blacklisting",
        ]
    elif company_key == "ct_us":
        tender.documents_needed = [
            "Certificate of Incorporation",
            "EIN / Tax ID Document",
            "SAM.gov Registration (CAGE Code)",
            "Past Performance References (2-3 projects)",
            "Technical Proposal (Signed)",
            "Cost Proposal (Signed)",
            "Key Personnel Resumes",
        ]
    else:
        tender.documents_needed = [
            "ACRA Business Profile",
            "UEN Number Document",
            "GeBIZ Vendor Registration",
            "Technical Proposal (Signed)",
            "Cost Proposal (Signed)",
            "Key Personnel Resumes",
        ]

    # Store all analysis data for PDF generation
    tender.raw_data["analysis"] = analysis
    tender.raw_data["cost_estimate"] = cost_estimate
    tender.raw_data["org_research"] = org_research
    tender.raw_data["executive_summary"] = exec_summary
    tender.raw_data["technical_approach"] = tech_approach

    logger.info("  Analysis complete: %s → %s (%s, %s)",
                 tender.title[:50], company["short"],
                 tender.complexity, tender.estimated_cost)

    return tender


async def search_contacts(tender: Tender) -> Tender:
    """Try to find contact information using SearXNG."""
    if tender.contact_email:
        return tender

    try:
        results = await _search_web(f"{tender.organization} procurement contact email {tender.country}")
        for r in results:
            snippet = r.get("content", "") + r.get("title", "")
            email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', snippet)
            if email_match:
                tender.contact_email = email_match.group(0)
                break
            phone_match = re.search(r'[\+\d][\d\s\-().]{8,}', snippet)
            if phone_match and not tender.contact_phone:
                tender.contact_phone = phone_match.group(0).strip()
    except Exception as e:
        logger.debug("Contact search failed: %s", e)

    return tender
