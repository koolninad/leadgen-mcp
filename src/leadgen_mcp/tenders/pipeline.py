"""Tender Intelligence Pipeline — crawl → analyze → PDF → Telegram.

Usage:
    from leadgen_mcp.tenders.pipeline import run_tender_scan
    await run_tender_scan()

CLI:
    PYTHONPATH=./src python3 -m leadgen_mcp.tenders.pipeline
"""

import asyncio
import logging
import time

from ..config import settings
from .analyzer import analyze_tender, search_contacts
from .models import Tender
from .notifier import send_tender_notification
from .proposal import generate_proposal_pdf

logger = logging.getLogger("tenders.pipeline")


async def crawl_all_sources(max_per_source: int = 15) -> list[Tender]:
    """Crawl all tender sources."""
    all_tenders = []

    sources = [
        # Priority 1: Must work
        ("UK Contracts", _crawl_uk, max_per_source),
        ("India (CPPP+GeM+States)", _crawl_india, max_per_source),
        ("Middle East (UAE+Saudi+Oman+Bahrain)", _crawl_middle_east, max_per_source),
        ("Southeast Asia (SG+Philippines)", _crawl_southeast_asia, max_per_source),
        ("SAM.gov (USA)", _crawl_sam_gov, max_per_source),
        # Priority 2: Nice to have
        ("EU TED", _crawl_eu, max_per_source),
        ("Multilateral (WB+UNGM)", _crawl_multilateral, max_per_source),
    ]

    for name, crawl_fn, max_r in sources:
        try:
            logger.info("Crawling %s...", name)
            tenders = await crawl_fn(max_r)
            all_tenders.extend(tenders)
            logger.info("  %s: %d tenders", name, len(tenders))
        except Exception as e:
            logger.error("  %s FAILED: %s", name, e)

    # Filter: only keep tenders with future deadlines (at least tomorrow)
    from datetime import datetime, timedelta, timezone
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    future_tenders = []
    expired = 0
    no_deadline = 0
    for t in all_tenders:
        if not t.deadline:
            # No deadline specified — include it (might be open-ended)
            no_deadline += 1
            future_tenders.append(t)
            continue

        # Parse deadline — try multiple formats
        deadline_str = t.deadline.strip()[:10]
        deadline_valid = False
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                dl = datetime.strptime(deadline_str, fmt)
                if dl.strftime("%Y-%m-%d") >= tomorrow:
                    future_tenders.append(t)
                    deadline_valid = True
                else:
                    expired += 1
                    deadline_valid = True
                break
            except ValueError:
                continue

        if not deadline_valid:
            # Can't parse date — include it to be safe
            future_tenders.append(t)

    if expired:
        logger.info("Filtered out %d expired tenders (deadline before %s)", expired, tomorrow)

    # Deduplicate by title similarity
    seen_titles = set()
    unique = []
    for t in future_tenders:
        key = t.title.lower()[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(t)

    logger.info("Total: %d unique tenders from %d raw (%d expired, %d no deadline)",
                len(unique), len(all_tenders), expired, no_deadline)
    return unique


async def _crawl_sam_gov(max_results):
    from .sources.sam_gov import crawl
    return await crawl(max_results=max_results)


async def _crawl_uk(max_results):
    from .sources.uk_contracts import crawl
    return await crawl(max_results=max_results)


async def _crawl_india(max_results):
    from .sources.cppp_india import crawl
    return await crawl(max_results=max_results)


async def _crawl_eu(max_results):
    from .sources.eu_ted import crawl
    return await crawl(max_results=max_results)


async def _crawl_middle_east(max_results):
    from .sources.middle_east import crawl
    return await crawl(max_results=max_results)


async def _crawl_southeast_asia(max_results):
    from .sources.southeast_asia import crawl
    return await crawl(max_results=max_results)


async def _crawl_multilateral(max_results):
    from .sources.multilateral import crawl
    return await crawl(max_results=max_results)


async def run_tender_scan(max_per_source: int = 15) -> dict:
    """Full tender pipeline: crawl → analyze → PDF → Telegram.

    Returns stats dict.
    """
    t0 = time.monotonic()
    stats = {
        "tenders_found": 0,
        "analyzed": 0,
        "pdfs_generated": 0,
        "telegrams_sent": 0,
        "errors": 0,
    }

    logger.info("=" * 50)
    logger.info("TENDER INTELLIGENCE SCAN")
    logger.info("=" * 50)

    # Step 1: Crawl all sources
    tenders = await crawl_all_sources(max_per_source)
    stats["tenders_found"] = len(tenders)

    if not tenders:
        logger.info("No tenders found")
        return stats

    # Step 1.5: Filter out already-sent tenders (dedup across daily runs)
    if settings.database_url:
        try:
            from ..db.pg_repository import get_pool
            from ..db.pg_schema import create_schema
            import hashlib

            pool = await get_pool()
            await create_schema(pool)

            new_tenders = []
            for t in tenders:
                title_hash = hashlib.md5(f"{t.title[:100]}:{t.source}".encode()).hexdigest()
                exists = await pool.fetchrow(
                    "SELECT id FROM tenders_sent WHERE title_hash = $1", title_hash
                )
                if not exists:
                    new_tenders.append(t)

            skipped = len(tenders) - len(new_tenders)
            if skipped:
                logger.info("Skipped %d already-sent tenders", skipped)
            tenders = new_tenders
        except Exception as e:
            logger.debug("Dedup check failed: %s", e)

    if not tenders:
        logger.info("No new tenders to process")
        return stats

    # Step 2: Analyze each tender with Gemma4
    for i, tender in enumerate(tenders, 1):
        logger.info("[%d/%d] Analyzing: %s", i, len(tenders), tender.title[:60])

        try:
            # AI analysis
            tender = await analyze_tender(tender)
            stats["analyzed"] += 1

            # Search for contacts
            tender = await search_contacts(tender)

            # Generate PDF proposal
            try:
                pdf_bytes = generate_proposal_pdf(tender)
                stats["pdfs_generated"] += 1
                logger.info("  PDF generated (%d KB)", len(pdf_bytes) // 1024)
            except Exception as e:
                logger.warning("  PDF generation failed: %s", e)
                pdf_bytes = None
                stats["errors"] += 1

            # Send to Telegram
            try:
                result = await send_tender_notification(tender, pdf_bytes)
                if result.get("card"):
                    stats["telegrams_sent"] += 1
            except Exception as e:
                logger.warning("  Telegram failed: %s", e)
                stats["errors"] += 1

            # Save to DB so we don't re-send tomorrow
            if settings.database_url:
                try:
                    import hashlib
                    from ..db.pg_repository import get_pool
                    pool = await get_pool()
                    title_hash = hashlib.md5(f"{tender.title[:100]}:{tender.source}".encode()).hexdigest()
                    await pool.execute(
                        """INSERT INTO tenders_sent (title_hash, source, title, organization, country, deadline, telegram_sent, pdf_sent)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                           ON CONFLICT (title_hash) DO NOTHING""",
                        title_hash, tender.source, tender.title[:200], tender.organization[:200],
                        tender.country, tender.deadline, True, pdf_bytes is not None,
                    )
                except Exception:
                    pass

            # Rate limit between tenders (Gemma4 is slow + Telegram rate limits)
            await asyncio.sleep(2)

        except Exception as e:
            logger.error("  Analysis failed: %s", e)
            stats["errors"] += 1

    elapsed = time.monotonic() - t0
    logger.info("=" * 50)
    logger.info("TENDER SCAN COMPLETE in %.0fs", elapsed)
    logger.info("  Found: %d | Analyzed: %d | PDFs: %d | Telegrams: %d | Errors: %d",
                stats["tenders_found"], stats["analyzed"],
                stats["pdfs_generated"], stats["telegrams_sent"], stats["errors"])
    logger.info("=" * 50)

    return stats


# CLI entry point
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_tender_scan())
