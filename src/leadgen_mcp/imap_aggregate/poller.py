"""IMAP polling — fetch unseen messages from all sender accounts."""

import asyncio
import email as email_lib
import email.utils
import imaplib
import json
import logging
from pathlib import Path

from ..config import settings
from ..db.pg_repository import get_pool, get_all_senders, save_reply
from ..notifications.telegram import send_lead_notification, flush_queue
from .classifier import classify_message

logger = logging.getLogger("leadgen.imap.poller")


class IMAPAggregator:
    """Polls all sender accounts via IMAP, classifies replies, stores in reply_inbox."""

    def __init__(self):
        self._running = False
        self._poll_count = 0

    async def run_forever(self):
        """Continuously poll all accounts."""
        self._running = True
        interval = settings.imap_poll_interval
        logger.info("IMAP aggregator starting (poll every %ds)", interval)

        while self._running:
            try:
                await self.poll_all()
            except Exception as e:
                logger.error("IMAP poll cycle error: %s", e, exc_info=True)

            waited = 0
            while waited < interval and self._running:
                await asyncio.sleep(1)
                waited += 1

        logger.info("IMAP aggregator stopped")

    def stop(self):
        self._running = False

    async def poll_all(self) -> dict:
        """Poll all sender accounts once. Returns stats."""
        self._poll_count += 1
        stats = {"accounts_polled": 0, "messages_found": 0, "replies": 0, "bounces": 0, "auto_replies": 0}

        senders = await get_all_senders()
        if not senders:
            return stats

        for sender in senders:
            if not sender.get("imap_host") or not sender.get("is_enabled"):
                continue

            try:
                count = await self._poll_account(sender)
                stats["accounts_polled"] += 1
                stats["messages_found"] += count
            except Exception as e:
                logger.warning("IMAP poll failed for %s: %s", sender["email"], e)

        await flush_queue()
        return stats

    async def _poll_account(self, account: dict) -> int:
        """Poll one IMAP account, return number of new messages."""
        loop = asyncio.get_event_loop()
        raw_messages = await loop.run_in_executor(
            None,
            _imap_fetch_unseen,
            account.get("imap_host", settings.nubo_imap_host),
            account.get("imap_port", settings.nubo_imap_port),
            account.get("smtp_user", account["email"]),
            account["smtp_password"],
        )

        if not raw_messages:
            return 0

        count = 0
        pool = await get_pool()

        for raw_msg in raw_messages:
            try:
                parsed = email_lib.message_from_bytes(raw_msg)
                from_addr = email_lib.utils.parseaddr(parsed.get("From", ""))[1]
                subject = parsed.get("Subject", "")
                message_id = parsed.get("Message-ID", "")

                # Extract body
                body = _extract_body(parsed)

                # Extract headers for classification
                headers = {
                    "auto-submitted": parsed.get("Auto-Submitted", ""),
                    "x-auto-response-suppress": parsed.get("X-Auto-Response-Suppress", ""),
                    "precedence": parsed.get("Precedence", ""),
                }

                # Classify
                classification = classify_message(from_addr, subject, body, headers)

                # Try to match to a lead
                lead_id = None
                if from_addr:
                    domain = from_addr.split("@")[1] if "@" in from_addr else None
                    if domain:
                        row = await pool.fetchrow(
                            "SELECT id FROM leads WHERE domain = $1", domain
                        )
                        if row:
                            lead_id = row["id"]

                # Save to reply_inbox
                saved = await save_reply(
                    from_email=from_addr,
                    to_account=account["email"],
                    subject=subject,
                    body=body[:5000],  # cap body size
                    message_id=message_id,
                    lead_id=lead_id,
                    is_auto_reply=classification["is_auto_reply"],
                    is_bounce=classification["is_bounce"],
                    is_unsubscribe=classification["is_unsubscribe"],
                )

                # Forward real replies to Telegram
                if classification["is_real_reply"] and saved:
                    await _notify_reply(from_addr, account["email"], subject, body, lead_id)

                count += 1

            except Exception as e:
                logger.warning("Failed to process message for %s: %s", account["email"], e)

        if count:
            logger.info("Processed %d messages for %s", count, account["email"])

        return count


async def _notify_reply(
    from_email: str, to_account: str, subject: str, body: str, lead_id: str | None,
):
    """Send reply notification to Telegram."""
    body_preview = body[:300] if body else ""
    card = {
        "source_platform": "reply",
        "company_name": from_email,
        "domain": from_email.split("@")[1] if "@" in from_email else "",
        "description": f"Reply to {to_account}\n\nSubject: {subject}\n\n{body_preview}",
        "_email_status": "replied",
    }
    if lead_id:
        card["_lead_id"] = lead_id
    await send_lead_notification(card)


def _imap_fetch_unseen(host: str, port: int, user: str, password: str) -> list[bytes]:
    """Blocking IMAP fetch of unseen messages."""
    try:
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
    except Exception as e:
        logger.debug("IMAP error for %s: %s", user, e)
        return []


def _extract_body(msg) -> str:
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        # Fallback to HTML
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    import re
                    html = payload.decode(charset, errors="replace")
                    return re.sub(r"<[^>]+>", "", html)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""
