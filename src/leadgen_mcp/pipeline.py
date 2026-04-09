"""Autonomous lead generation pipeline - runs without any AI client.

Chains together: discover -> scan -> enrich -> score -> email
in a fully automated loop that can run 24/7.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import settings
from .db.repository import (
    get_db,
    upsert_lead,
    get_lead,
    query_leads,
    get_contacts,
    save_scan_result,
)
from .platforms.tools import CRAWLERS, _save_leads
from .scanner.crawler import crawl_url, crawl_batch
from .scanner.tech_detector import detect_tech_stack
from .scanner.performance import analyze_performance
from .scanner.security import analyze_security
from .scanner.accessibility import analyze_accessibility
from .scanner.features import analyze_features
from .enrichment.email_finder import find_emails_for_domain
from .enrichment.contacts import find_decision_makers
from .enrichment.company_intel import get_company_intel
from .enrichment.scoring import score_lead
from .ai.email_generator import generate_outreach_email
from .email_sender.campaign import send_single_email
from .utils.validators import normalize_url, extract_domain
from .notifications.telegram import send_lead_notification, send_cycle_summary, flush_queue

logger = logging.getLogger("leadgen.pipeline")


@dataclass
class PipelineConfig:
    """Configuration for the autonomous pipeline."""

    # Which platforms to crawl
    platforms: list[str] = field(
        default_factory=lambda: [
            "hackernews", "reddit", "producthunt", "indiehackers",
        ]
    )

    # Search queries per platform: {platform: {param: value}}
    queries: dict[str, dict] = field(default_factory=dict)

    # Scoring
    min_score_to_email: float = 40.0  # Only email leads scored 40+

    # Email
    email_template: str = "tech_audit"
    max_emails_per_cycle: int = 20
    dry_run: bool = True  # Don't actually send emails by default

    # Scanning
    scan_concurrency: int = 5

    # Scheduling
    cycle_interval_hours: float = 6.0  # Run every 6 hours

    @classmethod
    def default_queries(cls) -> dict[str, dict]:
        """Return sensible default queries for each platform."""
        return {
            "hackernews": {
                "action": "hiring",
                "keywords": ["looking for developer"],
                "max_results": 30,
            },
            "reddit": {
                "action": "search",
                "keywords": ["looking for developer", "[Hiring]"],
                "subreddits": [
                    "forhire", "startups", "webdev", "entrepreneur",
                    "smallbusiness",
                ],
                "max_results": 30,
            },
            "producthunt": {
                "topics": ["saas", "developer-tools", "productivity"],
                "days_back": 30,
                "min_upvotes": 50,
                "max_results": 20,
            },
            "indiehackers": {
                "keywords": [
                    "looking for developer",
                    "need developer",
                    "technical cofounder",
                ],
                "max_results": 20,
            },
            "upwork": {
                "category": "software_development",
                "skills": [],
                "min_budget": 5000,
                "max_results": 30,
            },
            "clutch": {
                "category": "web_development",
                "location": "",
                "min_budget": 0,
                "max_results": 30,
            },
            "linkedin": {
                "action": "jobs",
                "keywords": ["software developer", "web application"],
                "max_results": 20,
            },
            "wellfound": {
                "industry": "software",
                "stage": "",
                "max_results": 20,
            },
            "crunchbase": {
                "stage": "seed",
                "industry": "",
                "keywords": [],
                "max_results": 20,
            },
            "github_projects": {
                "action": "abandoned",
                "min_stars": 100,
                "language": "",
                "keywords": ["help wanted"],
                "max_results": 20,
            },
            "twitter": {
                "keywords": [
                    "looking for developer",
                    "need a website",
                    "our app is broken",
                    "need a CTO",
                ],
                "max_results": 20,
            },
            "google_maps": {
                "action": "no_website",
                "category": "restaurant",
                "city": "",
                "max_results": 20,
            },
        }


@dataclass
class CycleStats:
    """Statistics for a single pipeline cycle."""

    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0

    # Discovery
    leads_discovered: int = 0
    leads_per_platform: dict[str, int] = field(default_factory=dict)
    discovery_errors: dict[str, str] = field(default_factory=dict)

    # Scanning
    websites_scanned: int = 0
    scan_successes: int = 0
    scan_failures: int = 0

    # Enrichment
    leads_enriched: int = 0
    emails_found: int = 0
    contacts_found: int = 0

    # Scoring
    leads_scored: int = 0
    hot_leads: int = 0  # score >= 70
    warm_leads: int = 0  # score >= 40
    cold_leads: int = 0  # score < 40

    # Email
    emails_generated: int = 0
    emails_sent: int = 0
    emails_failed: int = 0
    email_dry_run: bool = True

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": round(self.duration_seconds, 1),
            "discovery": {
                "total": self.leads_discovered,
                "per_platform": self.leads_per_platform,
                "errors": self.discovery_errors,
            },
            "scanning": {
                "total": self.websites_scanned,
                "successes": self.scan_successes,
                "failures": self.scan_failures,
            },
            "enrichment": {
                "leads_enriched": self.leads_enriched,
                "emails_found": self.emails_found,
                "contacts_found": self.contacts_found,
            },
            "scoring": {
                "leads_scored": self.leads_scored,
                "hot": self.hot_leads,
                "warm": self.warm_leads,
                "cold": self.cold_leads,
            },
            "email": {
                "generated": self.emails_generated,
                "sent": self.emails_sent,
                "failed": self.emails_failed,
                "dry_run": self.email_dry_run,
            },
        }

    def summary_lines(self) -> list[str]:
        """Return a human-readable summary."""
        lines = [
            f"Pipeline cycle completed in {self.duration_seconds:.1f}s",
            "",
            "--- Discovery ---",
        ]
        for platform, count in self.leads_per_platform.items():
            lines.append(f"  {platform}: {count} leads")
        for platform, err in self.discovery_errors.items():
            lines.append(f"  {platform}: FAILED - {err}")
        lines.append(f"  Total: {self.leads_discovered} leads")
        lines.append("")
        lines.append("--- Scanning ---")
        lines.append(
            f"  {self.websites_scanned} websites scanned "
            f"({self.scan_successes} ok, {self.scan_failures} failed)"
        )
        lines.append("")
        lines.append("--- Enrichment ---")
        lines.append(
            f"  {self.leads_enriched} leads enriched, "
            f"{self.emails_found} emails found, "
            f"{self.contacts_found} contacts found"
        )
        lines.append("")
        lines.append("--- Scoring ---")
        lines.append(
            f"  {self.leads_scored} scored: "
            f"{self.hot_leads} hot / {self.warm_leads} warm / {self.cold_leads} cold"
        )
        lines.append("")
        lines.append("--- Email ---")
        if self.email_dry_run:
            lines.append(
                f"  {self.emails_generated} emails generated (DRY RUN - not sent)"
            )
        else:
            lines.append(
                f"  {self.emails_generated} generated, "
                f"{self.emails_sent} sent, {self.emails_failed} failed"
            )
        return lines


class LeadGenPipeline:
    """Full autonomous pipeline: discover -> scan -> enrich -> score -> email."""

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig()
        # Fill in default queries for platforms that don't have custom ones
        defaults = PipelineConfig.default_queries()
        for platform in self.config.platforms:
            if platform not in self.config.queries and platform in defaults:
                self.config.queries[platform] = defaults[platform]

    async def _ensure_db(self):
        """Make sure the database is initialized."""
        await get_db()

    async def run_full_cycle(self) -> CycleStats:
        """Run one complete cycle: discover leads, scan, enrich, score, email."""
        stats = CycleStats(
            started_at=datetime.now(timezone.utc).isoformat(),
            email_dry_run=self.config.dry_run,
        )
        t0 = time.monotonic()

        await self._ensure_db()

        # Step 1: Discover leads from all configured platforms
        logger.info("Step 1/5: Discovering leads from %d platforms...",
                     len(self.config.platforms))
        leads = await self.discover_leads(stats)
        logger.info("Discovered %d leads total", len(leads))

        # Step 2: Scan websites for leads with domains
        logger.info("Step 2/5: Scanning websites...")
        leads = await self.scan_leads(leads, stats)
        logger.info("Scanned %d websites (%d ok, %d failed)",
                     stats.websites_scanned, stats.scan_successes,
                     stats.scan_failures)

        # Step 3: Enrich leads
        logger.info("Step 3/5: Enriching leads...")
        leads = await self.enrich_leads(leads, stats)
        logger.info("Enriched %d leads", stats.leads_enriched)

        # Step 4: Score all leads
        logger.info("Step 4/5: Scoring leads...")
        scored = await self.score_leads(leads, stats)
        logger.info("Scored %d leads: %d hot, %d warm, %d cold",
                     stats.leads_scored, stats.hot_leads,
                     stats.warm_leads, stats.cold_leads)

        # Step 5: Generate + send emails for hot leads
        hot_leads = [l for l in scored if l.get("_score_total", 0) >= self.config.min_score_to_email]
        logger.info("Step 5/5: Processing %d leads above score threshold %.0f...",
                     len(hot_leads), self.config.min_score_to_email)
        await self.generate_and_send(hot_leads, stats)

        # Send Telegram notification for EVERY lead with full details
        for i, lead in enumerate(scored, 1):
            try:
                await send_lead_notification(lead, lead_number=i)
            except Exception as e:
                logger.debug("Telegram notification failed for lead %d: %s", i, e)

        stats.finished_at = datetime.now(timezone.utc).isoformat()
        stats.duration_seconds = time.monotonic() - t0

        # Log summary
        for line in stats.summary_lines():
            logger.info(line)

        # Send cycle summary to Telegram
        try:
            await send_cycle_summary(stats.to_dict())
        except Exception as e:
            logger.debug("Telegram cycle summary failed: %s", e)

        # Wait for all Telegram messages to be sent
        try:
            await flush_queue()
        except Exception as e:
            logger.debug("Telegram queue flush failed: %s", e)

        return stats

    async def discover_leads(self, stats: CycleStats | None = None) -> list[dict]:
        """Crawl all configured platforms for new leads."""
        if stats is None:
            stats = CycleStats()

        all_leads: list[dict] = []

        for platform in self.config.platforms:
            if platform not in CRAWLERS:
                logger.warning("Unknown platform: %s — skipping", platform)
                stats.discovery_errors[platform] = "unknown platform"
                continue

            query_params = self.config.queries.get(platform, {})
            logger.info("  Crawling %s with params: %s", platform,
                        {k: v for k, v in query_params.items() if k != "keywords"})

            try:
                crawler = CRAWLERS[platform]()
                # Merge keywords into the query params if not already set
                if "keywords" not in query_params:
                    query_params["keywords"] = ["looking for developer"]
                if "max_results" not in query_params:
                    query_params["max_results"] = 30

                raw_leads = await crawler.safe_crawl(query_params)
                saved = await _save_leads(raw_leads)

                stats.leads_per_platform[platform] = len(saved)
                stats.leads_discovered += len(saved)
                all_leads.extend(saved)

                logger.info("  %s: found %d leads", platform, len(saved))
            except Exception as e:
                logger.error("  %s: crawl failed — %s", platform, e)
                stats.discovery_errors[platform] = str(e)
                stats.leads_per_platform[platform] = 0

        return all_leads

    async def scan_leads(self, leads: list[dict],
                         stats: CycleStats | None = None) -> list[dict]:
        """Scan websites for all leads that have domains."""
        if stats is None:
            stats = CycleStats()

        # Collect leads with domains
        scannable = [(i, lead) for i, lead in enumerate(leads) if lead.get("domain")]
        if not scannable:
            logger.info("  No leads with domains to scan")
            return leads

        urls = [normalize_url(lead["domain"]) for _, lead in scannable]
        stats.websites_scanned = len(urls)

        # Batch scan with concurrency
        results = await crawl_batch(urls, concurrency=self.config.scan_concurrency)

        for (idx, lead), cr in zip(scannable, results):
            lead_id = lead.get("lead_id") or lead.get("id")
            if not lead_id:
                continue

            if cr.success:
                stats.scan_successes += 1
                try:
                    tech = detect_tech_stack(cr.html, cr.headers)
                    perf = analyze_performance(cr)
                    security = analyze_security(cr)
                    accessibility = analyze_accessibility(cr.html)
                    features = await analyze_features(cr.html, cr.url, cr.headers)

                    # Save scan results to database
                    await save_scan_result(lead_id, "tech_stack", tech, "info")
                    await save_scan_result(
                        lead_id, "performance", perf,
                        perf.get("severity", "info")
                    )
                    await save_scan_result(
                        lead_id, "security", security,
                        security.get("severity", "info")
                    )
                    await save_scan_result(
                        lead_id, "accessibility", accessibility,
                        accessibility.get("severity", "info")
                    )
                    await save_scan_result(
                        lead_id, "features", features,
                        features.get("severity", "info")
                    )

                    leads[idx]["_scan_success"] = True
                    leads[idx]["_tech_stack"] = tech
                except Exception as e:
                    logger.error("  Scan analysis failed for %s: %s",
                                 lead.get("domain"), e)
                    stats.scan_failures += 1
                    leads[idx]["_scan_success"] = False
            else:
                stats.scan_failures += 1
                leads[idx]["_scan_success"] = False
                logger.debug("  Scan failed for %s: %s",
                             lead.get("domain"), cr.error)

        return leads

    async def enrich_leads(self, leads: list[dict],
                           stats: CycleStats | None = None) -> list[dict]:
        """Find emails, contacts, company intel for each lead."""
        if stats is None:
            stats = CycleStats()

        for lead in leads:
            domain = lead.get("domain")
            lead_id = lead.get("lead_id") or lead.get("id")
            if not domain or not lead_id:
                continue

            try:
                # Find emails
                email_results = await find_emails_for_domain(
                    domain, lead.get("company_name")
                )
                found_emails = email_results.get("emails_found", [])
                stats.emails_found += len(found_emails)

                from .db.repository import save_contact
                for email in found_emails:
                    await save_contact(
                        lead_id, email=email,
                        source="website_scrape", email_verified=False,
                    )

                # Find decision makers
                contacts = await find_decision_makers(domain)
                stats.contacts_found += len(contacts)
                for contact in contacts:
                    await save_contact(
                        lead_id,
                        name=contact.get("name"),
                        title=contact.get("title"),
                        source=contact.get("source", "website"),
                    )

                # Company intelligence
                intel = await get_company_intel(domain)
                await save_scan_result(lead_id, "company_intel", intel, "info")

                stats.leads_enriched += 1
                lead["_enriched"] = True
                lead["_emails_found"] = found_emails
            except Exception as e:
                logger.error("  Enrichment failed for %s: %s", domain, e)
                lead["_enriched"] = False

        return leads

    async def score_leads(self, leads: list[dict],
                          stats: CycleStats | None = None) -> list[dict]:
        """Score all leads and annotate with tier."""
        if stats is None:
            stats = CycleStats()

        for lead in leads:
            lead_id = lead.get("lead_id") or lead.get("id")
            if not lead_id:
                continue

            try:
                result = await score_lead(lead_id)
                if "error" in result:
                    logger.warning("  Scoring error for %s: %s",
                                   lead_id, result["error"])
                    continue

                total = result.get("total_score", 0)
                lead["_score_total"] = total
                lead["_score_tier"] = result.get("tier", "cold")
                stats.leads_scored += 1

                if total >= 70:
                    stats.hot_leads += 1
                elif total >= 40:
                    stats.warm_leads += 1
                else:
                    stats.cold_leads += 1
            except Exception as e:
                logger.error("  Scoring failed for %s: %s", lead_id, e)

        return leads

    async def generate_and_send(self, hot_leads: list[dict],
                                stats: CycleStats | None = None):
        """Generate personalized emails and send to hot leads."""
        if stats is None:
            stats = CycleStats()

        sent_count = 0
        for lead in hot_leads:
            if sent_count >= self.config.max_emails_per_cycle:
                logger.info("  Reached max emails per cycle (%d)",
                            self.config.max_emails_per_cycle)
                break

            lead_id = lead.get("lead_id") or lead.get("id")
            if not lead_id:
                continue

            # Get contact emails
            contacts = await get_contacts(lead_id)
            emails = [c["email"] for c in contacts if c.get("email")]
            if not emails:
                emails = lead.get("_emails_found", [])
            if not emails:
                logger.debug("  No email for lead %s — skipping", lead_id)
                continue

            to_email = emails[0]  # Use first available email

            try:
                # Generate email via AI
                email_data = await generate_outreach_email(
                    lead_id, self.config.email_template,
                )
                if "error" in email_data:
                    logger.warning("  Email generation failed for %s: %s",
                                   lead_id, email_data["error"])
                    stats.emails_failed += 1
                    continue

                stats.emails_generated += 1

                if self.config.dry_run:
                    logger.info(
                        "  [DRY RUN] Would send to %s: %s",
                        to_email, email_data.get("subject", "?"),
                    )
                else:
                    result = await send_single_email(
                        to_email=to_email,
                        subject=email_data["subject"],
                        body=email_data["body"],
                        lead_id=lead_id,
                        track=True,
                    )
                    if result.get("success"):
                        stats.emails_sent += 1
                        logger.info("  Sent email to %s", to_email)
                    else:
                        stats.emails_failed += 1
                        logger.warning("  Send failed for %s: %s",
                                       to_email, result.get("error"))

                sent_count += 1
            except Exception as e:
                logger.error("  Email flow failed for lead %s: %s", lead_id, e)
                stats.emails_failed += 1
