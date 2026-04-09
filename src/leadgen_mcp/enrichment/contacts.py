"""Decision-maker contact extraction from websites."""

import re

from bs4 import BeautifulSoup

from ..utils.http import create_client


# Titles indicating decision-makers
DECISION_MAKER_TITLES = [
    r"CEO", r"CTO", r"COO", r"CFO", r"CMO",
    r"Chief\s+(?:Executive|Technology|Operating|Financial|Marketing)\s+Officer",
    r"Founder", r"Co-Founder", r"Co-founder",
    r"President", r"Vice\s+President",
    r"VP\s+(?:of\s+)?(?:Engineering|Technology|Product|Development|IT)",
    r"Director\s+(?:of\s+)?(?:Engineering|Technology|IT|Development|Product|Operations)",
    r"Head\s+(?:of\s+)?(?:Engineering|Technology|IT|Development|Product)",
    r"Managing\s+Director",
    r"General\s+Manager",
    r"Partner",
    r"Owner",
]

TITLE_PATTERN = re.compile("|".join(DECISION_MAKER_TITLES), re.IGNORECASE)


async def find_decision_makers(domain: str) -> list[dict]:
    """Scrape company website for team/about pages to find decision-makers."""
    pages_to_check = [
        f"https://{domain}/about",
        f"https://{domain}/about-us",
        f"https://{domain}/team",
        f"https://{domain}/our-team",
        f"https://{domain}/leadership",
        f"https://{domain}/people",
        f"https://{domain}/company",
    ]

    contacts = []

    async with create_client(timeout=15.0) as client:
        for url in pages_to_check:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                found = _extract_contacts_from_html(resp.text, url)
                contacts.extend(found)
            except Exception:
                continue

    # Deduplicate by name
    seen = set()
    unique = []
    for c in contacts:
        key = c["name"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique


def _extract_contacts_from_html(html: str, source_url: str) -> list[dict]:
    """Extract names and titles from HTML content."""
    soup = BeautifulSoup(html, "lxml")
    contacts = []

    # Strategy 1: Look for team member cards/sections
    # Common patterns: div with image + name + title
    team_selectors = [
        ".team-member", ".team-card", ".member-card",
        ".staff-member", ".person", ".leadership-card",
        "[class*='team']", "[class*='member']",
        ".about-team li", ".team-grid > div",
    ]

    for selector in team_selectors:
        for card in soup.select(selector):
            contact = _parse_team_card(card, source_url)
            if contact:
                contacts.append(contact)

    # Strategy 2: Look for structured patterns in text
    # "Name, Title" or "Name - Title" patterns
    if not contacts:
        text = soup.get_text()
        for match in re.finditer(
            r"([A-Z][a-z]+ (?:[A-Z]\.? )?[A-Z][a-z]+)\s*[,\-–|]\s*(" + TITLE_PATTERN.pattern + r")",
            text
        ):
            name = match.group(1).strip()
            title = match.group(2).strip()
            if len(name) < 50:  # Sanity check
                contacts.append({
                    "name": name,
                    "title": title,
                    "source": source_url,
                    "is_decision_maker": True,
                })

    # Strategy 3: Find any mention of decision-maker titles near names
    if not contacts:
        for heading in soup.find_all(["h2", "h3", "h4", "strong", "b"]):
            name_text = heading.get_text(strip=True)
            if re.match(r"^[A-Z][a-z]+ (?:[A-Z]\.? )?[A-Z][a-z]+$", name_text):
                # Look for title in next sibling
                next_el = heading.find_next_sibling()
                if next_el:
                    title_text = next_el.get_text(strip=True)
                    if TITLE_PATTERN.search(title_text):
                        contacts.append({
                            "name": name_text,
                            "title": title_text[:100],
                            "source": source_url,
                            "is_decision_maker": True,
                        })

    return contacts


def _parse_team_card(card, source_url: str) -> dict | None:
    """Parse a team member card element."""
    # Try to find name
    name_el = card.select_one(
        "h3, h4, h2, .name, .member-name, [class*='name'], strong"
    )
    if not name_el:
        return None

    name = name_el.get_text(strip=True)
    if not name or len(name) > 60 or not re.search(r"[A-Z]", name):
        return None

    # Try to find title
    title_el = card.select_one(
        ".title, .position, .role, .job-title, [class*='title'], [class*='position'], p, span"
    )
    title = title_el.get_text(strip=True) if title_el else ""

    # Only include if this is a decision-maker
    is_dm = bool(TITLE_PATTERN.search(title))

    if is_dm:
        return {
            "name": name,
            "title": title[:100],
            "source": source_url,
            "is_decision_maker": True,
        }

    return None
