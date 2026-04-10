"""Seed account management for warmup.

Seed accounts receive warmup emails and auto-reply to them,
building sender reputation. The seed accounts are your own
email addresses on different domains that you control.
"""

import asyncio
import email
import imaplib
import logging
import random
import smtplib
from email.mime.text import MIMEText

from ..config import settings

logger = logging.getLogger("leadgen.warmup.seed")

# Warmup email subjects — varied to look natural
WARMUP_SUBJECTS = [
    "Quick question about your availability",
    "Following up on our earlier conversation",
    "Checking in — any updates?",
    "Re: Project timeline",
    "Meeting notes from today",
    "Thanks for the intro!",
    "Thoughts on this approach?",
    "Can you take a look at this?",
    "Re: Next steps",
    "Quick update on progress",
    "Coffee next week?",
    "Interesting article — thought of you",
    "Re: Budget discussion",
    "Just saw your message",
    "Good morning — a few thoughts",
]

WARMUP_BODIES = [
    "Hi there,\n\nJust wanted to check in and see how things are going on your end. Let me know if you need anything.\n\nBest regards",
    "Hey,\n\nThanks for getting back to me. I'll review the details and follow up by end of week.\n\nCheers",
    "Hi,\n\nI was thinking about what you mentioned and I think we should schedule a call to discuss further. What does your week look like?\n\nTalk soon",
    "Hello,\n\nGood news — we're making progress on the project. I'll send over the updated timeline tomorrow.\n\nBest",
    "Hi,\n\nWanted to share this article I came across. Thought it might be relevant to what we discussed.\n\nRegards",
    "Hey,\n\nJust a quick note to say thanks for the introduction. Looking forward to connecting with them.\n\nAll the best",
    "Hi,\n\nI reviewed the proposal and have a few thoughts. Can we hop on a quick call tomorrow?\n\nThanks",
    "Hello,\n\nJust following up on my last email. No rush, but wanted to make sure it didn't get buried.\n\nBest",
]


def generate_warmup_email() -> tuple[str, str]:
    """Generate a random warmup email subject and body."""
    return random.choice(WARMUP_SUBJECTS), random.choice(WARMUP_BODIES)


async def send_warmup_email(
    from_email: str,
    from_name: str,
    to_email: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
) -> bool:
    """Send a warmup email from a sender account to a seed account."""
    subject, body = generate_warmup_email()

    msg = MIMEText(body, "plain")
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _smtp_send, msg, smtp_host, smtp_port, smtp_user, smtp_password)
        logger.info("Warmup email sent: %s -> %s [%s]", from_email, to_email, subject)
        return True
    except Exception as e:
        logger.warning("Warmup email failed: %s -> %s: %s", from_email, to_email, e)
        return False


def _smtp_send(msg: MIMEText, host: str, port: int, user: str, password: str) -> None:
    """Blocking SMTP send (run in executor)."""
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)


async def check_and_reply_seed(
    imap_host: str,
    imap_port: int,
    imap_user: str,
    imap_password: str,
    smtp_host: str,
    smtp_port: int,
) -> int:
    """Check a seed account for warmup emails and auto-reply.

    Returns number of replies sent.
    """
    loop = asyncio.get_event_loop()
    try:
        messages = await loop.run_in_executor(
            None, _imap_fetch_unseen, imap_host, imap_port, imap_user, imap_password
        )
    except Exception as e:
        logger.warning("IMAP fetch failed for %s: %s", imap_user, e)
        return 0

    replied = 0
    for raw_msg in messages:
        try:
            parsed = email.message_from_bytes(raw_msg)
            from_addr = email.utils.parseaddr(parsed["From"])[1]
            subject = parsed.get("Subject", "")

            # Auto-reply
            reply_subject = f"Re: {subject}" if not subject.startswith("Re:") else subject
            reply_body = random.choice([
                "Thanks for the update! I'll take a look.",
                "Got it, thanks! Will get back to you soon.",
                "Appreciate the follow-up. Let me review and respond.",
                "Thanks! Noted.",
                "Great, thanks for sharing. I'll review this.",
            ])

            reply_msg = MIMEText(reply_body, "plain")
            reply_msg["From"] = f"{imap_user}"
            reply_msg["To"] = from_addr
            reply_msg["Subject"] = reply_subject
            reply_msg["In-Reply-To"] = parsed.get("Message-ID", "")

            await loop.run_in_executor(
                None, _smtp_send, reply_msg, smtp_host, smtp_port, imap_user, imap_password
            )
            replied += 1
            logger.info("Seed auto-reply: %s -> %s", imap_user, from_addr)
        except Exception as e:
            logger.warning("Seed reply failed: %s", e)

    return replied


def _imap_fetch_unseen(host: str, port: int, user: str, password: str) -> list[bytes]:
    """Blocking IMAP fetch of unseen messages."""
    conn = imaplib.IMAP4_SSL(host, port)
    conn.login(user, password)
    conn.select("INBOX")
    _, msg_nums = conn.search(None, "UNSEEN")
    messages = []
    if msg_nums[0]:
        for num in msg_nums[0].split():
            _, data = conn.fetch(num, "(RFC822)")
            if data and data[0]:
                messages.append(data[0][1])
            conn.store(num, "+FLAGS", "\\Seen")
    conn.logout()
    return messages
