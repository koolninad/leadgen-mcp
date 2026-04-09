"""Email open and click tracking injection."""

import re
from urllib.parse import quote

from ..config import settings


def inject_tracking(html: str, tracking_id: str) -> str:
    """Inject open tracking pixel and click tracking into HTML email."""
    base_url = settings.tracking_base_url.rstrip("/")

    # 1. Open tracking: inject 1x1 transparent pixel before </body>
    pixel = (
        f'<img src="{base_url}/track/open/{tracking_id}.png" '
        f'width="1" height="1" style="display:none" alt="" />'
    )

    if "</body>" in html.lower():
        html = re.sub(
            r"(</body>)",
            f"{pixel}\\1",
            html,
            flags=re.IGNORECASE,
        )
    else:
        html += pixel

    # 2. Click tracking: rewrite <a href="..."> links
    def rewrite_link(match):
        original_url = match.group(1)
        # Don't track mailto: or unsubscribe links
        if original_url.startswith("mailto:") or "unsubscribe" in original_url.lower():
            return match.group(0)
        tracked_url = f"{base_url}/track/click/{tracking_id}?url={quote(original_url)}"
        return f'href="{tracked_url}"'

    html = re.sub(r'href="([^"]+)"', rewrite_link, html)

    return html


def generate_tracking_id() -> str:
    """Generate a unique tracking ID."""
    import uuid
    return uuid.uuid4().hex[:16]
