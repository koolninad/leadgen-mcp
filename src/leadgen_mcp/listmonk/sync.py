"""Sync leads to Listmonk as subscribers, create campaigns per vertical."""

import logging

from ..config import settings
from ..db.pg_repository import get_pool, query_leads
from .client import ListmonkClient

logger = logging.getLogger("leadgen.listmonk.sync")

# Vertical → Listmonk list name mapping
VERTICAL_LIST_NAMES = {
    "hostingduty": "HostingDuty Leads",
    "chandorkar": "Chandorkar Technologies Leads",
    "nubo": "Nubo Email Leads",
    "vikasit": "Vikasit AI Leads",
    "setara": "Setara Blockchain Leads",
    "staff_aug": "Staff Augmentation Leads",
}


async def ensure_lists(client: ListmonkClient) -> dict[str, int]:
    """Ensure all vertical lists exist in Listmonk. Returns {vertical: list_id}."""
    existing = await client.get_lists()
    existing_names = {}
    if "data" in existing and "results" in existing["data"]:
        for lst in existing["data"]["results"]:
            existing_names[lst["name"]] = lst["id"]

    result = {}
    for vertical, name in VERTICAL_LIST_NAMES.items():
        if name in existing_names:
            result[vertical] = existing_names[name]
        else:
            resp = await client.create_list(
                name=name, type="private", optin="single",
                description=f"Auto-generated leads for {vertical}",
            )
            if "data" in resp:
                result[vertical] = resp["data"]["id"]
                logger.info("Created Listmonk list: %s (id=%d)", name, result[vertical])
            else:
                logger.error("Failed to create list %s: %s", name, resp)

    return result


async def sync_leads_to_listmonk(
    client: ListmonkClient | None = None,
    min_score: float = 40.0,
    vertical: str | None = None,
) -> dict:
    """Export scored leads with contacts as Listmonk subscribers.

    Returns: {"subscribers_created": int, "lists_synced": int, "errors": int}
    """
    if client is None:
        client = ListmonkClient()

    stats = {"subscribers_created": 0, "lists_synced": 0, "errors": 0}

    # Ensure lists exist
    list_map = await ensure_lists(client)
    stats["lists_synced"] = len(list_map)

    pool = await get_pool()

    # Get leads with contacts that have emails
    query = """
        SELECT l.id, l.company_name, l.domain, l.vertical_match,
               c.email, c.name, c.title,
               COALESCE(ls.total_score, 0) as score
        FROM leads l
        JOIN contacts c ON c.lead_id = l.id
        LEFT JOIN lead_scores ls ON ls.lead_id = l.id
        WHERE c.email IS NOT NULL
          AND COALESCE(ls.total_score, 0) >= $1
    """
    params = [min_score]

    if vertical:
        query += " AND $2 = ANY(l.vertical_match)"
        params.append(vertical)

    query += " ORDER BY score DESC LIMIT 500"

    rows = await pool.fetch(query, *params)

    for r in rows:
        email_addr = r["email"]
        name = r["name"] or r["company_name"] or email_addr.split("@")[0]

        # Determine which lists to add to
        verticals = r["vertical_match"] or []
        target_lists = [list_map[v] for v in verticals if v in list_map]
        if not target_lists:
            # Default to chandorkar (software dev)
            target_lists = [list_map.get("chandorkar", list(list_map.values())[0])]

        resp = await client.create_subscriber(
            email=email_addr,
            name=name,
            lists=target_lists,
            attribs={
                "company": r["company_name"],
                "domain": r["domain"],
                "title": r["title"],
                "score": float(r["score"]),
                "lead_id": r["id"],
            },
        )

        if "data" in resp:
            stats["subscribers_created"] += 1
        elif "already exists" in str(resp.get("error", "")):
            pass  # duplicate, fine
        else:
            stats["errors"] += 1
            logger.warning("Failed to create subscriber %s: %s", email_addr, resp)

    logger.info("Listmonk sync: %d subscribers, %d lists, %d errors",
                stats["subscribers_created"], stats["lists_synced"], stats["errors"])
    return stats


async def create_campaign_for_vertical(
    client: ListmonkClient,
    vertical: str,
    subject: str,
    body_html: str,
    from_email: str | None = None,
    campaign_name: str | None = None,
) -> dict:
    """Create a Listmonk campaign targeting a specific vertical's list."""
    list_map = await ensure_lists(client)
    list_id = list_map.get(vertical)
    if not list_id:
        return {"error": f"No list found for vertical: {vertical}"}

    name = campaign_name or f"{VERTICAL_LIST_NAMES.get(vertical, vertical)} Campaign"

    resp = await client.create_campaign(
        name=name,
        subject=subject,
        body=body_html,
        list_ids=[list_id],
        from_email=from_email,
    )

    if "data" in resp:
        campaign_id = resp["data"]["id"]
        logger.info("Created campaign: %s (id=%d) for %s", name, campaign_id, vertical)
        return {"campaign_id": campaign_id, "name": name, "vertical": vertical}

    return {"error": str(resp)}
