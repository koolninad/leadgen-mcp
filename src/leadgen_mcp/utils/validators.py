"""URL, email, and domain validation helpers."""

import re
from urllib.parse import urlparse


EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)

DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))


def is_valid_domain(domain: str) -> bool:
    return bool(DOMAIN_RE.match(domain.strip()))


def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False


def normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def extract_domain(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    domain = parsed.netloc
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def clean_email(email: str) -> str:
    return email.strip().lower()
