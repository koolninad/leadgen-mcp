"""PDF Proposal Generator — creates ready-to-submit tender proposals."""

import io
import logging
import os
from datetime import datetime

from .models import Tender, COMPANIES

logger = logging.getLogger("tenders.proposal")


def generate_proposal_pdf(tender: Tender) -> bytes:
    """Generate a PDF proposal for a tender. Returns PDF bytes.

    Uses reportlab if available, falls back to simple text-based PDF.
    """
    try:
        return _generate_with_reportlab(tender)
    except ImportError:
        return _generate_simple_pdf(tender)


def _generate_with_reportlab(tender: Tender) -> bytes:
    """Generate PDF using reportlab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch, mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=25*mm, bottomMargin=25*mm,
                            leftMargin=25*mm, rightMargin=25*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'],
                                  fontSize=18, spaceAfter=12, textColor=colors.HexColor('#1a237e'))
    h2_style = ParagraphStyle('CustomH2', parent=styles['Heading2'],
                               fontSize=14, spaceAfter=8, textColor=colors.HexColor('#283593'),
                               borderWidth=0, borderPadding=0)
    body_style = styles['BodyText']
    body_style.fontSize = 10
    body_style.leading = 14

    company_key = tender.recommended_company or "ct_india"
    company = COMPANIES.get(company_key, COMPANIES["ct_india"])
    cost_data = tender.raw_data.get("cost_estimate", {})
    analysis = tender.raw_data.get("analysis", {})

    elements = []

    # ── Cover Page ──
    elements.append(Spacer(1, 60))
    elements.append(Paragraph("TECHNICAL & FINANCIAL PROPOSAL", title_style))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"<b>{tender.title}</b>", styles['Heading3']))
    elements.append(Spacer(1, 15))

    cover_data = [
        ["Submitted To:", tender.organization],
        ["Reference:", tender.reference_number or "As per tender document"],
        ["Submitted By:", company["name"]],
        ["Date:", datetime.now().strftime("%B %d, %Y")],
        ["Country:", tender.country],
    ]
    if tender.deadline:
        cover_data.append(["Deadline:", tender.deadline])

    cover_table = Table(cover_data, colWidths=[120, 340])
    cover_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(cover_table)
    elements.append(Spacer(1, 30))

    # Company info box
    elements.append(Paragraph(f"<b>{company['name']}</b>", body_style))
    elements.append(Paragraph(f"{company['address']}", body_style))
    if company.get("gst"):
        elements.append(Paragraph(f"GST: {company['gst']} | PAN: {company.get('pan', '')}", body_style))
    if company.get("certifications"):
        elements.append(Paragraph(f"Certifications: {', '.join(company['certifications'])}", body_style))

    elements.append(PageBreak())

    # ── Table of Contents ──
    elements.append(Paragraph("TABLE OF CONTENTS", h2_style))
    toc = [
        "1. Cover Letter",
        "2. Executive Summary",
        "3. Company Profile",
        "4. Understanding of Requirements",
        "5. Technical Approach",
        "6. Team Composition",
        "7. Project Timeline & Milestones",
        "8. Cost Breakdown",
        "9. Risk Mitigation",
        "10. Document Checklist",
    ]
    for item in toc:
        elements.append(Paragraph(item, body_style))
    elements.append(PageBreak())

    # ── 1. Cover Letter ──
    elements.append(Paragraph("1. COVER LETTER", h2_style))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(f"Date: {datetime.now().strftime('%B %d, %Y')}", body_style))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(f"To,<br/>{tender.organization}<br/>{tender.country}", body_style))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(f"Subject: Proposal for {tender.title}", body_style))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(
        f"Dear Sir/Madam,<br/><br/>"
        f"We, <b>{company['name']}</b>, are pleased to submit our proposal for the above-mentioned "
        f"tender. With our proven expertise in IT services and software development, we are confident "
        f"in our ability to deliver this project successfully within the stipulated timeline and budget."
        f"<br/><br/>"
        f"We look forward to the opportunity to serve your organization."
        f"<br/><br/>"
        f"Yours faithfully,<br/>"
        f"<b>Authorized Signatory</b><br/>"
        f"{company['name']}",
        body_style
    ))
    elements.append(PageBreak())

    # ── 2. Executive Summary ──
    elements.append(Paragraph("2. EXECUTIVE SUMMARY", h2_style))
    elements.append(Paragraph(
        f"This proposal outlines our approach to deliver <b>{tender.title}</b> for "
        f"<b>{tender.organization}</b>. "
        f"Our assessment indicates this is a <b>{tender.complexity or 'medium'} complexity</b> project "
        f"requiring approximately <b>{tender.estimated_timeline or '4 months'}</b> with an estimated "
        f"investment of <b>{tender.estimated_cost or 'As per financial bid'}</b>.",
        body_style
    ))
    elements.append(Spacer(1, 8))

    if analysis.get("key_requirements"):
        elements.append(Paragraph(f"<b>Key Requirements:</b> {analysis['key_requirements']}", body_style))
    if analysis.get("recommended_approach"):
        elements.append(Paragraph(f"<b>Our Approach:</b> {analysis['recommended_approach']}", body_style))
    if tender.tech_stack_required:
        elements.append(Paragraph(f"<b>Technology Stack:</b> {', '.join(tender.tech_stack_required)}", body_style))
    elements.append(PageBreak())

    # ── 3. Company Profile ──
    elements.append(Paragraph("3. COMPANY PROFILE", h2_style))
    elements.append(Paragraph(f"<b>{company['name']}</b>", body_style))
    elements.append(Paragraph(f"Location: {company['address']}", body_style))
    if company.get("revenue_last_fy"):
        elements.append(Paragraph(f"Revenue (Last FY): {company['revenue_last_fy']}", body_style))
    elements.append(Spacer(1, 8))

    if company.get("certifications"):
        elements.append(Paragraph("<b>Certifications & Registrations:</b>", body_style))
        for cert in company["certifications"]:
            elements.append(Paragraph(f"  • {cert}", body_style))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph(
        "<b>Core Competencies:</b><br/>"
        "• Custom Software Development (Web, Mobile, Enterprise)<br/>"
        "• Cloud Infrastructure & Migration (AWS, Azure, GCP)<br/>"
        "• AI/ML Solutions & Data Analytics<br/>"
        "• Cybersecurity Audit & Implementation<br/>"
        "• E-Governance & Digital Transformation<br/>"
        "• Staff Augmentation & Managed IT Services",
        body_style
    ))
    elements.append(PageBreak())

    # ── 4. Understanding of Requirements ──
    elements.append(Paragraph("4. UNDERSTANDING OF REQUIREMENTS", h2_style))
    elements.append(Paragraph(
        f"Based on our analysis of the tender document, we understand the following:<br/><br/>"
        f"<b>Project:</b> {tender.title}<br/>"
        f"<b>Scope:</b> {tender.description[:400] or 'As defined in the tender document'}<br/>"
        f"<b>Technology:</b> {tender.technology or 'To be determined based on requirements'}<br/>"
        f"<b>Timeline:</b> {tender.estimated_timeline or 'As per tender specifications'}",
        body_style
    ))
    elements.append(PageBreak())

    # ── 5. Technical Approach ──
    elements.append(Paragraph("5. TECHNICAL APPROACH", h2_style))
    elements.append(Paragraph(
        "Our development methodology follows an Agile framework with the following phases:<br/><br/>"
        "<b>Phase 1: Discovery & Planning</b> (Week 1-2)<br/>"
        "• Requirement gathering and analysis<br/>"
        "• Stakeholder interviews<br/>"
        "• Technical architecture design<br/>"
        "• Project plan finalization<br/><br/>"
        "<b>Phase 2: Design & Prototyping</b> (Week 3-4)<br/>"
        "• UI/UX design and wireframes<br/>"
        "• Database schema design<br/>"
        "• API design and documentation<br/>"
        "• Prototype review with stakeholders<br/><br/>"
        "<b>Phase 3: Development</b> (Core implementation phase)<br/>"
        "• Sprint-based development (2-week sprints)<br/>"
        "• Regular demos and feedback cycles<br/>"
        "• Code review and quality assurance<br/>"
        "• Continuous integration and deployment<br/><br/>"
        "<b>Phase 4: Testing & QA</b><br/>"
        "• Unit testing, integration testing, system testing<br/>"
        "• Performance and security testing<br/>"
        "• User acceptance testing (UAT)<br/><br/>"
        "<b>Phase 5: Deployment & Handover</b><br/>"
        "• Production deployment<br/>"
        "• Knowledge transfer and training<br/>"
        "• Documentation handover<br/>"
        "• Post-deployment support",
        body_style
    ))
    elements.append(PageBreak())

    # ── 6. Team Composition ──
    elements.append(Paragraph("6. TEAM COMPOSITION", h2_style))
    if tender.team_composition:
        team_data = [["Role", "Count", "Duration", "Monthly Rate"]]
        for member in tender.team_composition:
            team_data.append([
                member["role"],
                str(member["count"]),
                f"{member['months']} months",
                f"{cost_data.get('currency', 'INR')} {member['monthly_rate']:,.0f}",
            ])

        team_table = Table(team_data, colWidths=[160, 50, 80, 120])
        team_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))
        elements.append(team_table)
    elements.append(PageBreak())

    # ── 7. Timeline ──
    elements.append(Paragraph("7. PROJECT TIMELINE & MILESTONES", h2_style))
    duration = cost_data.get("duration_months", 4)
    milestones = [
        ["Milestone", "Timeline", "Deliverables"],
        ["Project Kickoff", "Week 1", "Project Plan, Team Onboarding"],
        ["Requirements Sign-off", f"Week 2", "SRS Document, Use Cases"],
        ["Design Approval", f"Week {min(4, duration*4//5)}", "HLD, LLD, UI Mockups"],
        ["Development Complete", f"Month {max(2, duration-2)}", "Source Code, Unit Tests"],
        ["UAT Complete", f"Month {max(3, duration-1)}", "Test Reports, Bug Fixes"],
        ["Go-Live", f"Month {duration}", "Deployed System, Documentation"],
        ["Warranty Support", f"Month {duration}-{duration+3}", "Bug Fixes, Support"],
    ]

    ms_table = Table(milestones, colWidths=[140, 80, 240])
    ms_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
    ]))
    elements.append(ms_table)
    elements.append(PageBreak())

    # ── 8. Cost Breakdown ──
    elements.append(Paragraph("8. COST BREAKDOWN", h2_style))
    if cost_data:
        currency = cost_data.get("currency", "INR")
        cost_rows = [["Component", f"Amount ({currency})"]]

        for member in cost_data.get("breakdown", []):
            cost_rows.append([
                f"{member['role']} × {member['count']} ({member['months']} months)",
                f"{member['subtotal']:,.0f}",
            ])

        cost_rows.append(["Subtotal", f"{cost_data.get('subtotal', 0):,.0f}"])
        cost_rows.append(["Infrastructure & Overhead", f"{cost_data.get('overhead', 0):,.0f}"])
        cost_rows.append(["", ""])
        cost_rows.append(["TOTAL PROJECT COST", f"{cost_data.get('total', 0):,.0f}"])

        cost_table = Table(cost_rows, colWidths=[320, 140])
        cost_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8eaf6')),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ]))
        elements.append(cost_table)
    elements.append(PageBreak())

    # ── 9. Risk Mitigation ──
    elements.append(Paragraph("9. RISK MITIGATION", h2_style))
    risks = tender.risk_factors or [
        "Scope creep — mitigated by clear SRS sign-off",
        "Resource availability — mitigated by bench strength",
        "Technology changes — mitigated by modular architecture",
        "Timeline delays — mitigated by Agile methodology with buffer",
    ]
    for risk in risks:
        elements.append(Paragraph(f"• {risk}", body_style))
    elements.append(PageBreak())

    # ── 10. Document Checklist ──
    elements.append(Paragraph("10. DOCUMENT CHECKLIST", h2_style))
    elements.append(Paragraph("The following documents are to be attached with this proposal:", body_style))
    elements.append(Spacer(1, 8))

    docs = tender.documents_needed or ["As per tender requirements"]
    for i, doc_item in enumerate(docs, 1):
        elements.append(Paragraph(f"☐  {doc_item}", body_style))

    elements.append(Spacer(1, 20))
    elements.append(Paragraph(
        f"<b>Note:</b> Please print this proposal on company letterhead, attach the above documents, "
        f"and submit before the deadline: <b>{tender.deadline or 'As per tender document'}</b>.",
        body_style
    ))

    # Build PDF
    doc.build(elements)
    return buffer.getvalue()


def _generate_simple_pdf(tender: Tender) -> bytes:
    """Fallback: generate a simple text-based PDF without reportlab."""
    company_key = tender.recommended_company or "ct_india"
    company = COMPANIES.get(company_key, COMPANIES["ct_india"])
    cost_data = tender.raw_data.get("cost_estimate", {})

    lines = []
    lines.append("TECHNICAL & FINANCIAL PROPOSAL")
    lines.append("=" * 50)
    lines.append(f"Tender: {tender.title}")
    lines.append(f"Organization: {tender.organization}")
    lines.append(f"Country: {tender.country}")
    lines.append(f"Reference: {tender.reference_number}")
    lines.append(f"Deadline: {tender.deadline}")
    lines.append(f"Submitted By: {company['name']}")
    lines.append(f"Date: {datetime.now().strftime('%B %d, %Y')}")
    lines.append("")
    lines.append(f"Estimated Cost: {tender.estimated_cost}")
    lines.append(f"Timeline: {tender.estimated_timeline}")
    lines.append(f"Complexity: {tender.complexity}")
    lines.append(f"Technology: {tender.technology}")
    lines.append("")
    lines.append("DOCUMENT CHECKLIST:")
    for doc in (tender.documents_needed or []):
        lines.append(f"  [ ] {doc}")

    text = "\n".join(lines)

    # Minimal PDF structure
    pdf = b"%PDF-1.4\n"
    pdf += b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    pdf += b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    pdf += b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"

    # Text stream
    text_lines = text.split("\n")
    stream = "BT /F1 10 Tf 50 800 Td 12 TL\n"
    for line in text_lines[:60]:
        safe = line.replace("(", "\\(").replace(")", "\\)").replace("\\", "\\\\")
        stream += f"({safe}) '\n"
    stream += "ET\n"

    stream_bytes = stream.encode("latin-1", errors="replace")
    pdf += f"4 0 obj<</Length {len(stream_bytes)}>>stream\n".encode()
    pdf += stream_bytes
    pdf += b"\nendstream endobj\n"
    pdf += b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Courier>>endobj\n"
    pdf += b"xref\n0 6\n"
    pdf += b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"

    return pdf
