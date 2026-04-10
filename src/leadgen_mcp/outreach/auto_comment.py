"""Auto-comment on social platforms as an outreach channel.

For leads found on Reddit, LinkedIn, HN, IndieHackers, Quora etc —
where we can't get an email, we post a helpful comment with a soft pitch.

Approach:
- Generate a genuinely helpful comment via Gemma4 (NOT spammy)
- Post as a reply/comment on the source platform
- Track which posts we've already commented on (avoid duplicates)
- Rate limit heavily (1-2 comments per platform per hour)

Supported platforms:
- Reddit: via Reddit API (needs account + app credentials)
- HackerNews: via HN API (needs account)
- IndieHackers: via browser automation (Patchright)
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from ..config import settings
from ..db.pg_repository import get_pool

logger = logging.getLogger("leadgen.outreach.comment")

# Comment templates — Gemma4 will personalize these
COMMENT_PROMPTS = {
    "reddit": """Write a helpful Reddit comment replying to this post.

Post title: {title}
Post body: {description}
Subreddit: {subreddit}

Requirements:
- Be genuinely helpful first (answer their question or give advice)
- Mention relevant experience BRIEFLY (1 sentence max)
- Soft CTA at the end (e.g., "Feel free to DM if you want to chat more")
- DO NOT hard-sell or link-spam
- Sound like a real Redditor, not a marketer
- Keep under 100 words
- Sign off casually

Context: You work at {agency_name}, a software development company.
""",

    "hackernews": """Write a helpful Hacker News comment replying to this post.

Post title: {title}
Post content: {description}

Requirements:
- Add technical insight or a thoughtful perspective
- If relevant, mention your experience briefly
- HN audience is technical — don't oversimplify
- NO marketing language whatsoever
- Keep under 80 words
- Be concise and substantive

Context: You're a developer who works at {agency_name}.
""",

    "indiehackers": """Write a helpful IndieHackers comment replying to this post.

Post title: {title}
Post content: {description}

Requirements:
- Be supportive and constructive (IH culture is encouraging)
- Share actionable advice from experience
- Mention your background briefly if relevant
- Soft offer to help (e.g., "Happy to chat if you need a hand")
- Keep under 100 words

Context: You're a founder/developer at {agency_name}.
""",

    "quora": """Write a helpful Quora answer to this question.

Question: {title}
Details: {description}

Requirements:
- Give a thorough, useful answer
- Use your expertise to provide real value
- Mention your company/experience in context (not as a plug)
- Keep under 150 words
- Be professional but approachable

Context: You're a developer at {agency_name} ({agency_website}).
""",
}


async def generate_comment(
    platform: str,
    title: str,
    description: str,
    extra_context: dict | None = None,
) -> dict:
    """Generate a platform-appropriate comment via Gemma4.

    Returns: {"comment": str} or {"error": str}
    """
    from ..ai.ollama_client import generate as ollama_generate

    template = COMMENT_PROMPTS.get(platform)
    if not template:
        return {"error": f"No comment template for platform: {platform}"}

    prompt = template.format(
        title=title[:200],
        description=(description or "")[:500],
        subreddit=extra_context.get("subreddit", "") if extra_context else "",
        agency_name=settings.agency_name,
        agency_website=settings.agency_website,
    )

    try:
        response = await ollama_generate(
            prompt=prompt,
            system_prompt=(
                "You are writing a social media comment. Be genuine, helpful, and human. "
                "Never use corporate buzzwords. Never hard-sell. The goal is to be helpful "
                "first, and naturally build credibility."
            ),
            temperature=0.8,
            max_tokens=300,
        )
        return {"comment": response.strip()}
    except Exception as e:
        return {"error": str(e)}


async def post_reddit_comment(
    post_url: str,
    comment_text: str,
    reddit_username: str | None = None,
    reddit_password: str | None = None,
) -> dict:
    """Post a comment on Reddit via the JSON API.

    Requires Reddit account credentials. Uses Reddit's API with OAuth.
    """
    from ..utils.http import create_client

    username = reddit_username or settings.reddit_username if hasattr(settings, 'reddit_username') else ""
    password = reddit_password or settings.reddit_password if hasattr(settings, 'reddit_password') else ""

    if not username or not password:
        return {"error": "Reddit credentials not configured"}

    # Extract post ID from URL
    import re
    match = re.search(r"/comments/([a-z0-9]+)", post_url)
    if not match:
        return {"error": f"Cannot extract post ID from URL: {post_url}"}

    post_id = f"t3_{match.group(1)}"

    try:
        async with create_client(timeout=30.0) as client:
            # OAuth token
            auth_resp = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "password", "username": username, "password": password},
                auth=(settings.reddit_client_id if hasattr(settings, 'reddit_client_id') else "",
                      settings.reddit_client_secret if hasattr(settings, 'reddit_client_secret') else ""),
                headers={"User-Agent": f"LeadGen/1.0 by /u/{username}"},
            )
            if auth_resp.status_code != 200:
                return {"error": f"Reddit auth failed: {auth_resp.status_code}"}

            token = auth_resp.json().get("access_token")

            # Post comment
            comment_resp = await client.post(
                "https://oauth.reddit.com/api/comment",
                data={"thing_id": post_id, "text": comment_text},
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": f"LeadGen/1.0 by /u/{username}",
                },
            )

            if comment_resp.status_code == 200:
                return {"success": True, "platform": "reddit", "post_url": post_url}
            else:
                return {"error": f"Reddit comment failed: {comment_resp.status_code}"}

    except Exception as e:
        return {"error": str(e)}


async def should_comment(lead_id: str, platform: str) -> bool:
    """Check if we should comment on this lead (dedup + rate limit)."""
    pool = await get_pool()

    # Check if already commented
    row = await pool.fetchrow(
        """SELECT id FROM job_queue
           WHERE lead_id = $1 AND job_type = 'comment' AND status IN ('completed', 'processing')""",
        lead_id,
    )
    if row:
        return False

    # Rate limit: max 2 comments per platform per hour
    row = await pool.fetchrow(
        """SELECT COUNT(*) as c FROM job_queue
           WHERE job_type = 'comment'
             AND payload->>'platform' = $1
             AND status = 'completed'
             AND completed_at > NOW() - INTERVAL '1 hour'""",
        platform,
    )
    if row and row["c"] >= 2:
        return False

    return True


async def enqueue_comment(
    lead_id: str,
    platform: str,
    post_url: str,
    title: str,
    description: str,
    extra_context: dict | None = None,
) -> int | None:
    """Enqueue a comment job for a lead (if not already commented)."""
    if not await should_comment(lead_id, platform):
        return None

    from ..queue import enqueue
    job_id = await enqueue(
        job_type="comment",
        lead_id=lead_id,
        payload={
            "platform": platform,
            "post_url": post_url,
            "title": title,
            "description": description,
            "extra_context": extra_context or {},
        },
        priority=3,  # lower than email jobs
    )
    return job_id


async def handle_comment_job(job: dict) -> dict:
    """Queue worker handler for comment jobs."""
    lead_id = job["lead_id"]
    payload = job.get("payload", {})
    platform = payload["platform"]
    post_url = payload.get("post_url", "")
    title = payload.get("title", "")
    description = payload.get("description", "")
    extra_context = payload.get("extra_context", {})

    # Generate comment
    result = await generate_comment(platform, title, description, extra_context)
    if "error" in result:
        raise Exception(f"Comment generation failed: {result['error']}")

    comment_text = result["comment"]

    # For now, log the comment (actual posting requires platform credentials)
    # TODO: Implement actual posting for each platform when credentials are configured
    logger.info("Generated %s comment for %s: %s", platform, post_url[:60], comment_text[:100])

    # Send to Telegram so you can manually post if needed
    from ..notifications.telegram import send_lead_notification
    from ..db.pg_repository import get_lead

    lead = await get_lead(lead_id)
    if lead:
        lead["_email_status"] = "comment_generated"
        lead["_email_body"] = f"[{platform.upper()} COMMENT]\n\n{comment_text}"
        lead["_email_subject"] = f"Comment for: {title[:60]}"
        lead["_email_to"] = post_url
        lead["_verticals"] = lead.get("vertical_match") or ["chandorkar"]
        try:
            await send_lead_notification(lead)
        except Exception:
            pass

    return {
        "platform": platform,
        "comment": comment_text,
        "post_url": post_url,
        "posted": False,  # Will be True when actual posting is implemented
    }
