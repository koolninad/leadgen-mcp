"""MCP tool definitions for the AI Email Personalization module."""

from .ollama_client import check_health
from .email_generator import generate_outreach_email, generate_followup_sequence, refine_email
from .templates import list_templates


def register(mcp):
    """Register all AI email personalization tools with the MCP server."""

    @mcp.tool()
    async def ai_generate_outreach_email(lead_id: str, template: str = "tech_audit") -> dict:
        """Generate a personalized cold outreach email for a lead using AI (Gemma 4).
        Templates: tech_audit, project_match, growth_partner, modernization, security_alert.

        Args:
            lead_id: The lead ID to generate email for
            template: Email template to use (default: tech_audit)
        """
        return await generate_outreach_email(lead_id, template)

    @mcp.tool()
    async def ai_generate_followup_sequence(lead_id: str, num_emails: int = 3) -> dict:
        """Generate a complete follow-up email sequence (initial + follow-ups) for a lead.

        Args:
            lead_id: The lead ID to generate sequence for
            num_emails: Number of emails in the sequence (1 initial + follow-ups, max 4)
        """
        num_emails = min(num_emails, 4)
        sequence = await generate_followup_sequence(lead_id, num_emails)
        return {
            "lead_id": lead_id,
            "total_emails": len(sequence),
            "sequence": sequence,
        }

    @mcp.tool()
    async def ai_list_email_templates() -> dict:
        """List all available email templates with descriptions."""
        templates = list_templates()
        return {
            "total": len(templates),
            "templates": templates,
        }

    @mcp.tool()
    async def ai_preview_email(lead_id: str, template: str = "tech_audit") -> dict:
        """Preview a personalized email without sending it. Shows subject, body, and personalization notes.

        Args:
            lead_id: The lead ID to preview email for
            template: Email template to use
        """
        result = await generate_outreach_email(lead_id, template)
        if "error" in result:
            return result
        return {
            "preview": True,
            "subject": result["subject"],
            "body": result["body"],
            "personalization_notes": result.get("personalization_notes", []),
            "template_used": template,
        }

    @mcp.tool()
    async def ai_refine_email(email_draft: str, instructions: str) -> dict:
        """Refine an email draft with specific instructions using AI.

        Args:
            email_draft: The email text to refine (include Subject: line)
            instructions: What to change (e.g., 'make it shorter', 'add urgency', 'softer CTA')
        """
        return await refine_email(email_draft, instructions)

    @mcp.tool()
    async def ai_check_status() -> dict:
        """Check if the AI engine (Ollama + Gemma 4) is running and available."""
        return await check_health()
