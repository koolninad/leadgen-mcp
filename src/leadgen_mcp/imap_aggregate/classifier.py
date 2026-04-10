"""Classify email replies — real reply, auto-reply, bounce, unsubscribe."""

import re


# Auto-reply indicators
AUTO_REPLY_SUBJECTS = [
    re.compile(r"out of office", re.I),
    re.compile(r"automatic reply", re.I),
    re.compile(r"auto.?reply", re.I),
    re.compile(r"away from (the )?office", re.I),
    re.compile(r"on vacation", re.I),
    re.compile(r"maternity|paternity leave", re.I),
    re.compile(r"autorespond", re.I),
]

BOUNCE_SENDERS = [
    "mailer-daemon",
    "postmaster",
    "mail-daemon",
    "mailerdaemon",
]

BOUNCE_SUBJECTS = [
    re.compile(r"undeliverable", re.I),
    re.compile(r"delivery (status )?notification", re.I),
    re.compile(r"mail delivery failed", re.I),
    re.compile(r"returned mail", re.I),
    re.compile(r"failure notice", re.I),
    re.compile(r"delivery failure", re.I),
]

HARD_BOUNCE_PATTERNS = [
    re.compile(r"user unknown", re.I),
    re.compile(r"mailbox not found", re.I),
    re.compile(r"address rejected", re.I),
    re.compile(r"no such user", re.I),
    re.compile(r"does not exist", re.I),
    re.compile(r"invalid (mail)?box", re.I),
    re.compile(r"550 ", re.I),  # SMTP 550 permanent failure
]


def classify_message(
    from_addr: str,
    subject: str,
    body: str,
    headers: dict | None = None,
) -> dict:
    """Classify an incoming email.

    Returns:
        {
            "is_real_reply": bool,
            "is_auto_reply": bool,
            "is_bounce": bool,
            "is_unsubscribe": bool,
            "bounce_type": str | None,  # "hard" or "soft"
            "category": str,  # "reply", "auto_reply", "hard_bounce", "soft_bounce", "unsubscribe"
        }
    """
    headers = headers or {}
    from_lower = from_addr.lower()
    subject = subject or ""
    body = body or ""
    body_preview = body[:2000].lower()

    result = {
        "is_real_reply": False,
        "is_auto_reply": False,
        "is_bounce": False,
        "is_unsubscribe": False,
        "bounce_type": None,
        "category": "reply",
    }

    # Check Auto-Submitted header (RFC 3834)
    auto_submitted = headers.get("auto-submitted", "").lower()
    if auto_submitted and auto_submitted != "no":
        result["is_auto_reply"] = True
        result["category"] = "auto_reply"
        return result

    # Check X-Auto-Response-Suppress
    if headers.get("x-auto-response-suppress"):
        result["is_auto_reply"] = True
        result["category"] = "auto_reply"
        return result

    # Check Precedence header
    precedence = headers.get("precedence", "").lower()
    if precedence in ("bulk", "junk", "auto_reply"):
        result["is_auto_reply"] = True
        result["category"] = "auto_reply"
        return result

    # Check for bounce sender
    if any(b in from_lower for b in BOUNCE_SENDERS):
        result["is_bounce"] = True
        # Determine hard vs soft
        if any(p.search(body_preview) for p in HARD_BOUNCE_PATTERNS):
            result["bounce_type"] = "hard"
            result["category"] = "hard_bounce"
        else:
            result["bounce_type"] = "soft"
            result["category"] = "soft_bounce"
        return result

    # Check bounce subjects
    if any(p.search(subject) for p in BOUNCE_SUBJECTS):
        result["is_bounce"] = True
        if any(p.search(body_preview) for p in HARD_BOUNCE_PATTERNS):
            result["bounce_type"] = "hard"
            result["category"] = "hard_bounce"
        else:
            result["bounce_type"] = "soft"
            result["category"] = "soft_bounce"
        return result

    # Check auto-reply subjects
    if any(p.search(subject) for p in AUTO_REPLY_SUBJECTS):
        result["is_auto_reply"] = True
        result["category"] = "auto_reply"
        return result

    # Check for unsubscribe
    if "unsubscribe" in body_preview[:500] or "remove me" in body_preview[:500]:
        result["is_unsubscribe"] = True
        result["is_real_reply"] = True
        result["category"] = "unsubscribe"
        return result

    # If we got here, it's a real reply
    result["is_real_reply"] = True
    result["category"] = "reply"
    return result
