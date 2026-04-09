"""Lightweight tracking server for email open/click events.

Run with: uvicorn tracking_server.app:app --port 8899
"""

import asyncio
from urllib.parse import unquote

from fastapi import FastAPI, Response
from fastapi.responses import RedirectResponse

app = FastAPI(title="LeadGen Email Tracker", docs_url=None, redoc_url=None)

# In-memory event store (replace with DB in production)
_events: list[dict] = []

# 1x1 transparent PNG pixel
PIXEL = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@app.get("/track/open/{tracking_id}.png")
async def track_open(tracking_id: str):
    """Record email open event and return a transparent pixel."""
    _events.append({"type": "open", "tracking_id": tracking_id})

    # Update DB asynchronously
    asyncio.create_task(_record_open(tracking_id))

    return Response(content=PIXEL, media_type="image/png", headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    })


@app.get("/track/click/{tracking_id}")
async def track_click(tracking_id: str, url: str = ""):
    """Record click event and redirect to original URL."""
    original_url = unquote(url)
    _events.append({"type": "click", "tracking_id": tracking_id, "url": original_url})

    asyncio.create_task(_record_click(tracking_id))

    if original_url:
        return RedirectResponse(url=original_url, status_code=302)
    return {"status": "tracked"}


@app.get("/health")
async def health():
    return {"status": "ok", "events_recorded": len(_events)}


async def _record_open(tracking_id: str):
    """Record open event to database."""
    try:
        import aiosqlite
        from src.leadgen_mcp.config import settings
        async with aiosqlite.connect(settings.db_path) as db:
            await db.execute(
                "UPDATE emails_sent SET opened_at = datetime('now') WHERE tracking_id = ? AND opened_at IS NULL",
                (tracking_id,),
            )
            await db.commit()
    except Exception:
        pass


async def _record_click(tracking_id: str):
    """Record click event to database."""
    try:
        import aiosqlite
        from src.leadgen_mcp.config import settings
        async with aiosqlite.connect(settings.db_path) as db:
            await db.execute(
                "UPDATE emails_sent SET clicked_at = datetime('now') WHERE tracking_id = ? AND clicked_at IS NULL",
                (tracking_id,),
            )
            await db.commit()
    except Exception:
        pass
