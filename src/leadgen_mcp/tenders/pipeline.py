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

from .analyzer import analyze_tender, search_contacts
from .models import Tender
from .notifier import send_tender_notification
from .proposal import generate_proposal_pdf

logger = logging.getLogger("tenders.pipeline")


async def crawl_all_sources(max_per_source: int = 15) -> list[Tender]:
    """Crawl all tender sources."""
    all_tenders = []

    sources = [
        ("SAM.gov", _crawl_sam_gov, max_per_source),
        ("UK Contracts", _crawl_uk, max_per_source),
        ("India (CPPP+GeM)", _crawl_india, max_per_source),
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

    # Deduplicate by title similarity
    seen_titles = set()
    unique = []
    for t in all_tenders:
        key = t.title.lower()[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(t)

    logger.info("Total: %d unique tenders from %d raw", len(unique), len(all_tenders))
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
