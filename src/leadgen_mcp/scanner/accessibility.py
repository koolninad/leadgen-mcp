"""Website accessibility analysis (WCAG checks)."""

import re

from bs4 import BeautifulSoup


def analyze_accessibility(html: str) -> dict:
    """Analyze website for common accessibility issues."""
    soup = BeautifulSoup(html, "lxml")
    issues = []

    # 1. Missing alt attributes on images
    images = soup.find_all("img")
    no_alt = [img for img in images if not img.get("alt") and img.get("alt") != ""]
    if no_alt:
        issues.append({
            "issue": "Images missing alt text",
            "detail": f"{len(no_alt)}/{len(images)} images lack alt attributes",
            "severity": "warning",
            "wcag": "1.1.1",
        })

    # 2. Missing form labels
    inputs = soup.find_all("input", {"type": lambda t: t not in ("hidden", "submit", "button", "reset")})
    unlabeled = 0
    for inp in inputs:
        inp_id = inp.get("id")
        has_label = inp.get("aria-label") or inp.get("aria-labelledby") or inp.get("title")
        if inp_id:
            has_label = has_label or soup.find("label", {"for": inp_id})
        # Check if wrapped in label
        if not has_label and not inp.find_parent("label"):
            unlabeled += 1
    if unlabeled:
        issues.append({
            "issue": "Form inputs missing labels",
            "detail": f"{unlabeled} input fields lack associated labels",
            "severity": "warning",
            "wcag": "1.3.1",
        })

    # 3. Missing language attribute
    html_tag = soup.find("html")
    if html_tag and not html_tag.get("lang"):
        issues.append({
            "issue": "Missing language attribute",
            "detail": "<html> tag lacks lang attribute",
            "severity": "warning",
            "wcag": "3.1.1",
        })

    # 4. Heading hierarchy
    headings = soup.find_all(re.compile(r"^h[1-6]$"))
    heading_levels = [int(h.name[1]) for h in headings]
    if heading_levels:
        if heading_levels[0] != 1:
            issues.append({
                "issue": "First heading is not h1",
                "detail": f"Page starts with h{heading_levels[0]} instead of h1",
                "severity": "info",
                "wcag": "1.3.1",
            })
        for i in range(1, len(heading_levels)):
            if heading_levels[i] > heading_levels[i-1] + 1:
                issues.append({
                    "issue": "Heading level skipped",
                    "detail": f"h{heading_levels[i-1]} followed by h{heading_levels[i]} (skipped level)",
                    "severity": "info",
                    "wcag": "1.3.1",
                })
                break
    else:
        issues.append({
            "issue": "No headings found",
            "detail": "Page has no heading elements — poor document structure",
            "severity": "warning",
            "wcag": "1.3.1",
        })

    # 5. Missing skip navigation link
    first_links = soup.find_all("a", limit=5)
    has_skip = any("skip" in (l.get_text().lower() + l.get("href", "")) for l in first_links)
    if not has_skip:
        issues.append({
            "issue": "No skip navigation link",
            "detail": "Page lacks a 'skip to main content' link for keyboard users",
            "severity": "info",
            "wcag": "2.4.1",
        })

    # 6. Empty links/buttons
    empty_links = [a for a in soup.find_all("a") if not a.get_text(strip=True) and not a.find("img") and not a.get("aria-label")]
    if empty_links:
        issues.append({
            "issue": "Empty links found",
            "detail": f"{len(empty_links)} links have no text or aria-label",
            "severity": "warning",
            "wcag": "2.4.4",
        })

    empty_buttons = [b for b in soup.find_all("button") if not b.get_text(strip=True) and not b.get("aria-label")]
    if empty_buttons:
        issues.append({
            "issue": "Empty buttons found",
            "detail": f"{len(empty_buttons)} buttons have no text or aria-label",
            "severity": "warning",
            "wcag": "4.1.2",
        })

    # 7. Missing viewport meta
    viewport = soup.find("meta", {"name": "viewport"})
    if not viewport:
        issues.append({
            "issue": "Missing viewport meta tag",
            "detail": "No viewport meta tag — page may not be mobile-friendly",
            "severity": "warning",
            "wcag": "1.4.10",
        })

    # 8. Tabindex abuse
    tabindex_elements = soup.find_all(attrs={"tabindex": True})
    positive_tabindex = [el for el in tabindex_elements if el.get("tabindex", "0").lstrip("-").isdigit() and int(el["tabindex"]) > 0]
    if positive_tabindex:
        issues.append({
            "issue": "Positive tabindex values",
            "detail": f"{len(positive_tabindex)} elements have tabindex > 0 — disrupts natural tab order",
            "severity": "info",
            "wcag": "2.4.3",
        })

    # 9. ARIA roles check
    aria_elements = soup.find_all(attrs={"role": True})
    landmarks = [el for el in aria_elements if el["role"] in ("main", "navigation", "banner", "contentinfo")]
    if not landmarks:
        issues.append({
            "issue": "No ARIA landmarks",
            "detail": "Page lacks ARIA landmark roles (main, navigation, etc.)",
            "severity": "info",
            "wcag": "1.3.1",
        })

    severities = [i["severity"] for i in issues]
    if "critical" in severities:
        overall = "critical"
    elif "warning" in severities:
        overall = "warning"
    else:
        overall = "good"

    return {
        "issues": issues,
        "issue_count": len(issues),
        "severity": overall,
        "summary": {
            "total_images": len(images),
            "images_missing_alt": len(no_alt),
            "total_inputs": len(inputs),
            "inputs_missing_labels": unlabeled,
            "heading_count": len(headings),
            "has_lang": bool(html_tag and html_tag.get("lang")),
        },
    }
