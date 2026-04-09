"""CLI interface for the LeadGen autonomous pipeline.

Usage:
    leadgen run                     # Run a single pipeline cycle
    leadgen daemon                  # Run continuously (24/7)
    leadgen dashboard               # Live terminal dashboard
    leadgen discover                # Discover leads from platforms
    leadgen scan --url URL          # Scan a single website
    leadgen scan-batch --file F     # Scan URLs from a file
    leadgen enrich --lead-id ID     # Enrich a single lead
    leadgen score --all             # Score all unscored leads
    leadgen email --lead-id ID      # Generate + send email for a lead
    leadgen email-batch             # Email all leads above score threshold
    leadgen leads                   # List leads from database
    leadgen stats                   # Show aggregate stats
    leadgen campaigns               # Show campaigns
    leadgen config show             # Show current config
    leadgen config set KEY VALUE    # Update .env config
    leadgen domain-check DOMAIN     # Full domain intelligence scan
    leadgen dns-check DOMAIN        # DNS health check
    leadgen ssl-check DOMAIN        # SSL certificate check
    leadgen status                  # Server status
"""

import asyncio
import logging
import sys

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.panel import Panel

from .pipeline import LeadGenPipeline, PipelineConfig
from .scheduler import PipelineScheduler

console = Console()


def _setup_logging(verbose: bool = False):
    """Configure logging with rich console output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True,
                              show_path=False)],
    )
    # Quiet noisy libraries
    for name in ("httpx", "httpcore", "crawl4ai", "urllib3", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _run_async(coro):
    """Run an async coroutine, handling Windows event loop policy."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coro)


async def _ensure_db():
    """Initialize the database."""
    from .db.repository import get_db
    await get_db()


# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------

@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose):
    """LeadGen - Autonomous lead generation pipeline."""
    _setup_logging(verbose)


# ---------------------------------------------------------------------------
# run - single cycle
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--platforms", "-p", default=None,
              help="Comma-separated platforms (e.g. reddit,hackernews,producthunt)")
@click.option("--min-score", default=40.0, help="Minimum score to email (default: 40)")
@click.option("--max-emails", default=20, help="Max emails per cycle (default: 20)")
@click.option("--template", default="tech_audit", help="Email template")
@click.option("--dry-run/--send", default=True,
              help="Dry run mode (default: --dry-run)")
def run(platforms, min_score, max_emails, template, dry_run):
    """Run a single pipeline cycle."""
    config = PipelineConfig(
        min_score_to_email=min_score,
        max_emails_per_cycle=max_emails,
        email_template=template,
        dry_run=dry_run,
    )
    if platforms:
        config.platforms = [p.strip() for p in platforms.split(",")]

    pipeline = LeadGenPipeline(config)

    async def _run():
        scheduler = PipelineScheduler(pipeline)
        stats = await scheduler.run_single()
        _print_cycle_stats(stats)

    _run_async(_run())


# ---------------------------------------------------------------------------
# daemon - 24/7 mode
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--platforms", "-p", default=None,
              help="Comma-separated platforms")
@click.option("--interval", default=6.0,
              help="Hours between cycles (default: 6)")
@click.option("--min-score", default=40.0, help="Minimum score to email")
@click.option("--max-emails", default=20, help="Max emails per cycle")
@click.option("--template", default="tech_audit", help="Email template")
@click.option("--dry-run/--send", default=True, help="Dry run mode")
def daemon(platforms, interval, min_score, max_emails, template, dry_run):
    """Run the pipeline continuously (24/7 daemon mode)."""
    # Default to ALL platforms in daemon mode for full coverage
    all_platforms = list(PipelineConfig.default_queries().keys())
    config = PipelineConfig(
        platforms=all_platforms,
        cycle_interval_hours=interval,
        min_score_to_email=min_score,
        max_emails_per_cycle=max_emails,
        email_template=template,
        dry_run=dry_run,
    )
    if platforms:
        config.platforms = [p.strip() for p in platforms.split(",")]

    pipeline = LeadGenPipeline(config)
    scheduler = PipelineScheduler(pipeline)

    console.print(Panel(
        f"[bold]LeadGen Daemon[/bold]\n"
        f"Platforms: {', '.join(config.platforms)}\n"
        f"Interval: {interval}h | Min score: {min_score} | "
        f"Max emails/cycle: {max_emails}\n"
        f"Dry run: {dry_run} | Template: {template}\n\n"
        f"Press Ctrl+C to stop gracefully.",
        title="Starting 24/7 Pipeline",
        border_style="green",
    ))

    _run_async(scheduler.run_forever())


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--refresh", default=2.0, help="Refresh interval in seconds")
def dashboard(refresh):
    """Show live terminal dashboard."""
    from .dashboard import Dashboard
    dash = Dashboard(refresh_interval=refresh)
    _run_async(dash.run())


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--platforms", "-p",
              default="hackernews,reddit,producthunt,indiehackers",
              help="Comma-separated platforms")
@click.option("--max-results", default=30, help="Max results per platform")
def discover(platforms, max_results):
    """Discover leads from configured platforms."""
    platform_list = [p.strip() for p in platforms.split(",")]
    config = PipelineConfig(platforms=platform_list)
    # Override max_results in queries
    for p in platform_list:
        if p in config.queries:
            config.queries[p]["max_results"] = max_results

    pipeline = LeadGenPipeline(config)

    async def _run():
        await _ensure_db()
        from .pipeline import CycleStats
        stats = CycleStats()
        leads = await pipeline.discover_leads(stats)
        _print_leads_table(leads, f"Discovered {len(leads)} leads")
        for platform, count in stats.leads_per_platform.items():
            console.print(f"  {platform}: {count} leads")
        for platform, err in stats.discovery_errors.items():
            console.print(f"  [red]{platform}: FAILED - {err}[/red]")

    _run_async(_run())


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--url", required=True, help="URL to scan")
@click.option("--full/--quick", default=True, help="Full or quick scan")
def scan(url, full):
    """Scan a single website."""
    from .scanner.crawler import crawl_url
    from .scanner.tech_detector import detect_tech_stack
    from .scanner.performance import analyze_performance
    from .scanner.security import analyze_security
    from .scanner.accessibility import analyze_accessibility
    from .scanner.features import analyze_features
    from .utils.validators import normalize_url

    async def _run():
        await _ensure_db()
        url_n = normalize_url(url)
        console.print(f"Scanning [cyan]{url_n}[/cyan]...")
        result = await crawl_url(url_n)
        if not result.success:
            console.print(f"[red]Scan failed: {result.error}[/red]")
            return

        tech = detect_tech_stack(result.html, result.headers)
        console.print(Panel(str(tech), title="Tech Stack", border_style="cyan"))

        if full:
            perf = analyze_performance(result)
            sec = analyze_security(result)
            acc = analyze_accessibility(result.html)
            feat = await analyze_features(result.html, url_n, result.headers)

            _print_scan_section("Performance", perf)
            _print_scan_section("Security", sec)
            _print_scan_section("Accessibility", acc)
            _print_scan_section("Features", feat)

    _run_async(_run())


@cli.command("scan-batch")
@click.option("--file", "filepath", required=True,
              help="File with one URL per line")
@click.option("--concurrency", default=10, help="Concurrent scans")
def scan_batch(filepath, concurrency):
    """Scan multiple websites from a file."""
    from .scanner.crawler import crawl_batch
    from .scanner.tech_detector import detect_tech_stack
    from .utils.validators import normalize_url

    async def _run():
        await _ensure_db()
        with open(filepath) as f:
            urls = [normalize_url(line.strip()) for line in f if line.strip()]

        console.print(f"Scanning {len(urls)} URLs with concurrency={concurrency}...")
        results = await crawl_batch(urls, concurrency=concurrency)

        table = Table(title=f"Batch Scan Results ({len(urls)} URLs)")
        table.add_column("URL", width=40)
        table.add_column("Status")
        table.add_column("Load Time")
        table.add_column("Tech")

        ok = fail = 0
        for cr in results:
            if cr.success:
                ok += 1
                tech = detect_tech_stack(cr.html, cr.headers)
                techs = ", ".join(list(tech.get("frameworks", []))[:3])
                table.add_row(
                    cr.url[:40],
                    "[green]OK[/green]",
                    f"{cr.load_time_ms}ms",
                    techs or "-",
                )
            else:
                fail += 1
                table.add_row(cr.url[:40], f"[red]{cr.error}[/red]", "-", "-")

        console.print(table)
        console.print(f"\n{ok} succeeded, {fail} failed")

    _run_async(_run())


# ---------------------------------------------------------------------------
# enrich
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--lead-id", required=True, help="Lead ID to enrich")
def enrich(lead_id):
    """Enrich a single lead (emails, contacts, company intel)."""
    from .enrichment.email_finder import find_emails_for_domain
    from .enrichment.contacts import find_decision_makers
    from .enrichment.company_intel import get_company_intel
    from .enrichment.scoring import score_lead
    from .db.repository import get_lead, save_contact, save_scan_result

    async def _run():
        await _ensure_db()
        lead = await get_lead(lead_id)
        if not lead:
            console.print(f"[red]Lead {lead_id} not found[/red]")
            return

        domain = lead.get("domain")
        if not domain:
            console.print("[red]Lead has no domain[/red]")
            return

        console.print(f"Enriching lead [cyan]{lead_id}[/cyan] ({domain})...")

        emails = await find_emails_for_domain(domain, lead.get("company_name"))
        console.print(f"  Emails found: {emails.get('emails_found', [])}")

        contacts = await find_decision_makers(domain)
        console.print(f"  Decision makers: {len(contacts)}")

        intel = await get_company_intel(domain)
        console.print(f"  Company intel: {list(intel.keys())}")

        score_result = await score_lead(lead_id)
        console.print(
            f"  Score: [bold]{score_result.get('total_score', 'N/A')}[/bold] "
            f"({score_result.get('tier', '?')})"
        )

    _run_async(_run())


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--all", "score_all", is_flag=True, help="Score all leads")
@click.option("--lead-id", default=None, help="Score a specific lead")
def score(score_all, lead_id):
    """Score leads."""
    from .enrichment.scoring import score_lead
    from .db.repository import query_leads

    async def _run():
        await _ensure_db()
        if lead_id:
            result = await score_lead(lead_id)
            console.print(
                f"Lead {lead_id}: score={result.get('total_score', 'N/A')} "
                f"tier={result.get('tier', '?')}"
            )
            return

        if score_all:
            leads = await query_leads(min_score=0, limit=10000)
            console.print(f"Scoring {len(leads)} leads...")
            hot = warm = cold = 0
            for lead in leads:
                lid = lead.get("id")
                if not lid:
                    continue
                result = await score_lead(lid)
                total = result.get("total_score", 0)
                if total >= 70:
                    hot += 1
                elif total >= 40:
                    warm += 1
                else:
                    cold += 1

            console.print(
                f"\nScored {len(leads)} leads: "
                f"[green]{hot} hot[/green] / "
                f"[yellow]{warm} warm[/yellow] / "
                f"[dim]{cold} cold[/dim]"
            )

    _run_async(_run())


# ---------------------------------------------------------------------------
# email
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--lead-id", required=True, help="Lead ID")
@click.option("--template", default="tech_audit", help="Email template")
@click.option("--dry-run/--send", default=True, help="Dry run mode")
def email(lead_id, template, dry_run):
    """Generate and optionally send an email for a lead."""
    from .ai.email_generator import generate_outreach_email
    from .email_sender.campaign import send_single_email
    from .db.repository import get_contacts

    async def _run():
        await _ensure_db()
        console.print(f"Generating email for lead [cyan]{lead_id}[/cyan]...")
        result = await generate_outreach_email(lead_id, template)

        if "error" in result:
            console.print(f"[red]{result['error']}[/red]")
            return

        console.print(Panel(
            f"[bold]Subject:[/bold] {result['subject']}\n\n{result['body']}",
            title="Generated Email",
            border_style="green",
        ))

        if not dry_run:
            contacts = await get_contacts(lead_id)
            emails = [c["email"] for c in contacts if c.get("email")]
            if not emails:
                console.print("[red]No contact email found for this lead[/red]")
                return
            to = emails[0]
            send_result = await send_single_email(
                to_email=to, subject=result["subject"],
                body=result["body"], lead_id=lead_id,
            )
            if send_result.get("success"):
                console.print(f"[green]Email sent to {to}[/green]")
            else:
                console.print(f"[red]Send failed: {send_result.get('error')}[/red]")
        else:
            console.print("[yellow]DRY RUN - email not sent[/yellow]")

    _run_async(_run())


@cli.command("email-batch")
@click.option("--min-score", default=50.0, help="Minimum lead score")
@click.option("--template", default="tech_audit", help="Email template")
@click.option("--max-emails", default=20, help="Max emails to send")
@click.option("--dry-run/--send", default=True, help="Dry run mode")
def email_batch(min_score, template, max_emails, dry_run):
    """Generate and send emails to all leads above a score threshold."""
    config = PipelineConfig(
        min_score_to_email=min_score,
        email_template=template,
        max_emails_per_cycle=max_emails,
        dry_run=dry_run,
    )
    pipeline = LeadGenPipeline(config)

    async def _run():
        await _ensure_db()
        from .db.repository import query_leads
        leads = await query_leads(min_score=min_score, limit=max_emails)
        console.print(
            f"Found {len(leads)} leads with score >= {min_score}"
        )
        if not leads:
            return

        # Augment leads with required fields for generate_and_send
        for lead in leads:
            lead["lead_id"] = lead["id"]
            lead["_score_total"] = lead.get("score", 0)

        from .pipeline import CycleStats
        stats = CycleStats(email_dry_run=dry_run)
        await pipeline.generate_and_send(leads, stats)

        console.print(
            f"\nGenerated: {stats.emails_generated} | "
            f"Sent: {stats.emails_sent} | "
            f"Failed: {stats.emails_failed}"
        )
        if dry_run:
            console.print("[yellow]DRY RUN - no emails actually sent[/yellow]")

    _run_async(_run())


# ---------------------------------------------------------------------------
# leads
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--min-score", default=0.0, help="Minimum score filter")
@click.option("--source", default=None, help="Source platform filter")
@click.option("--domain", default=None, help="Domain substring filter")
@click.option("--limit", default=50, help="Max results")
def leads(min_score, source, domain, limit):
    """List leads from the database."""
    from .db.repository import query_leads

    async def _run():
        await _ensure_db()
        results = await query_leads(
            min_score=min_score,
            source_platform=source,
            domain_contains=domain,
            limit=limit,
        )
        _print_leads_table(results,
                           f"Leads (score >= {min_score}, limit {limit})")

    _run_async(_run())


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

@cli.command()
def stats():
    """Show aggregate pipeline statistics."""
    from .db.repository import query_leads, get_email_analytics

    async def _run():
        await _ensure_db()
        all_leads = await query_leads(min_score=0, limit=100000)
        analytics = await get_email_analytics(days=30)

        # Lead counts
        total = len(all_leads)
        hot = sum(1 for l in all_leads if l.get("score", 0) >= 70)
        warm = sum(1 for l in all_leads if 40 <= l.get("score", 0) < 70)
        cold = total - hot - warm

        # Source breakdown
        sources: dict[str, int] = {}
        for l in all_leads:
            s = l.get("source_platform", "unknown")
            sources[s] = sources.get(s, 0) + 1

        console.print(Panel(
            f"[bold]Total leads:[/bold] {total}\n"
            f"[green]Hot (70+):[/green] {hot}\n"
            f"[yellow]Warm (40-69):[/yellow] {warm}\n"
            f"[dim]Cold (<40):[/dim] {cold}",
            title="Lead Statistics",
            border_style="cyan",
        ))

        # Source table
        table = Table(title="Leads by Source")
        table.add_column("Platform", style="cyan")
        table.add_column("Count", justify="right")
        for s, c in sorted(sources.items(), key=lambda x: x[1], reverse=True):
            table.add_row(s, str(c))
        console.print(table)

        # Email stats
        total_sent = analytics.get("total_sent", 0) or 0
        total_opened = analytics.get("total_opened", 0) or 0
        total_clicked = analytics.get("total_clicked", 0) or 0

        console.print(Panel(
            f"[bold]Emails sent (30d):[/bold] {total_sent}\n"
            f"Opened: {total_opened}\n"
            f"Clicked: {total_clicked}\n"
            f"Open rate: "
            f"{total_opened / total_sent * 100:.1f}%" if total_sent else "N/A",
            title="Email Analytics",
            border_style="magenta",
        ))

    _run_async(_run())


# ---------------------------------------------------------------------------
# campaigns
# ---------------------------------------------------------------------------

@cli.command()
def campaigns():
    """Show email campaigns."""
    from .db.repository import get_db

    async def _run():
        db = await _ensure_db()
        db = await get_db()  # type: ignore
        rows = await db.execute_fetchall(
            "SELECT * FROM campaigns ORDER BY created_at DESC LIMIT 20"
        )
        if not rows:
            console.print("[dim]No campaigns found[/dim]")
            return

        table = Table(title="Email Campaigns")
        table.add_column("ID", width=12)
        table.add_column("Name", width=25)
        table.add_column("Status", width=10)
        table.add_column("Template", width=15)
        table.add_column("Created", width=20)

        for row in rows:
            r = dict(row)
            status = r.get("status", "?")
            style = {
                "active": "green",
                "paused": "yellow",
                "draft": "dim",
                "completed": "cyan",
            }.get(status, "")
            table.add_row(
                r.get("id", ""),
                r.get("name", ""),
                f"[{style}]{status}[/{style}]" if style else status,
                r.get("template", ""),
                (r.get("created_at", "") or "")[:19],
            )
        console.print(table)

    _run_async(_run())


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

@cli.group("config")
def config_group():
    """View or update configuration."""
    pass


@config_group.command("show")
def config_show():
    """Show current configuration from .env."""
    from .config import settings

    table = Table(title="Current Configuration")
    table.add_column("Setting", style="cyan", width=28)
    table.add_column("Value")

    fields = [
        ("ollama_base_url", settings.ollama_base_url),
        ("ollama_model", settings.ollama_model),
        ("smtp_host", settings.smtp_host),
        ("smtp_port", str(settings.smtp_port)),
        ("smtp_user", settings.smtp_user),
        ("smtp_from_name", settings.smtp_from_name),
        ("smtp_from_email", settings.smtp_from_email),
        ("db_path", settings.db_path),
        ("tracking_base_url", settings.tracking_base_url),
        ("max_scan_concurrency", str(settings.max_scan_concurrency)),
        ("max_platform_concurrency", str(settings.max_platform_concurrency)),
        ("email_rate_per_minute", str(settings.email_rate_per_minute)),
        ("email_rate_per_hour", str(settings.email_rate_per_hour)),
        ("agency_name", settings.agency_name),
        ("agency_website", settings.agency_website),
        ("agency_phone", settings.agency_phone),
        ("agency_address", settings.agency_address),
    ]

    for key, val in fields:
        # Mask passwords
        if "password" in key.lower() and val:
            val = val[:2] + "***" + val[-2:]
        table.add_row(key, val)

    console.print(table)


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a configuration value in .env file."""
    import os

    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    env_path = os.path.normpath(env_path)

    key_upper = key.upper()

    # Read existing .env
    lines = []
    found = False
    try:
        with open(env_path, "r") as f:
            for line in f:
                if line.strip().startswith(f"{key_upper}="):
                    lines.append(f"{key_upper}={value}\n")
                    found = True
                else:
                    lines.append(line)
    except FileNotFoundError:
        pass

    if not found:
        lines.append(f"{key_upper}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)

    console.print(f"[green]Set {key_upper}={value} in {env_path}[/green]")


# ---------------------------------------------------------------------------
# domain-check / dns-check / ssl-check
# ---------------------------------------------------------------------------

@cli.command("domain-check")
@click.argument("domain")
def domain_check(domain):
    """Run full domain intelligence scan (WHOIS, DNS, SSL, HTTP, links)."""
    from .domain_intel.whois_scanner import lookup_whois
    from .domain_intel.dns_checker import check_dns
    from .domain_intel.ssl_monitor import check_ssl
    from .domain_intel.http_monitor import check_http_health, find_broken_links

    async def _run():
        await _ensure_db()
        console.print(f"Running full domain scan on [cyan]{domain}[/cyan]...")

        import asyncio as _asyncio
        url = f"https://{domain}"

        whois_r, dns_r, ssl_r, http_r, links_r = await _asyncio.gather(
            lookup_whois(domain),
            _asyncio.to_thread(check_dns, domain),
            _asyncio.to_thread(check_ssl, domain),
            check_http_health(url),
            find_broken_links(url, max_links=30),
            return_exceptions=True,
        )

        def _show(name, result):
            if isinstance(result, Exception):
                console.print(f"[red]{name}: {result}[/red]")
            else:
                issues = result.get("issues", [])
                severity = result.get("severity", "ok")
                color = {"critical": "red", "warning": "yellow"}.get(
                    severity, "green"
                )
                console.print(Panel(
                    f"Severity: [{color}]{severity}[/{color}]\n"
                    f"Issues: {len(issues)}",
                    title=name,
                    border_style=color,
                ))
                for issue in issues[:5]:
                    console.print(f"  - {issue}")

        _show("WHOIS", whois_r)
        _show("DNS", dns_r)
        _show("SSL", ssl_r)
        _show("HTTP", http_r)
        _show("Broken Links", links_r)

    _run_async(_run())


@cli.command("dns-check")
@click.argument("domain")
def dns_check(domain):
    """Check DNS health for a domain."""
    from .domain_intel.dns_checker import check_dns

    async def _run():
        await _ensure_db()
        import asyncio as _asyncio
        console.print(f"Checking DNS for [cyan]{domain}[/cyan]...")
        result = await _asyncio.to_thread(check_dns, domain)

        table = Table(title=f"DNS Health: {domain}")
        table.add_column("Check", width=20)
        table.add_column("Status")
        table.add_column("Detail", width=40)

        for issue in result.get("issues", []):
            sev = issue.get("severity", "info")
            color = {"critical": "red", "warning": "yellow"}.get(sev, "green")
            table.add_row(
                issue.get("check", "?"),
                f"[{color}]{sev}[/{color}]",
                str(issue.get("detail", ""))[:40],
            )

        if not result.get("issues"):
            table.add_row("All checks", "[green]PASS[/green]", "No issues found")

        console.print(table)

    _run_async(_run())


@cli.command("ssl-check")
@click.argument("domain")
def ssl_check(domain):
    """Check SSL certificate for a domain."""
    from .domain_intel.ssl_monitor import check_ssl

    async def _run():
        await _ensure_db()
        import asyncio as _asyncio
        console.print(f"Checking SSL for [cyan]{domain}[/cyan]...")
        result = await _asyncio.to_thread(check_ssl, domain)

        table = Table(title=f"SSL Certificate: {domain}")
        table.add_column("Property", width=20, style="cyan")
        table.add_column("Value")

        for key in ("issuer", "subject", "expires", "days_until_expiry",
                     "protocol", "cipher", "severity"):
            if key in result:
                table.add_row(key, str(result[key]))

        console.print(table)

        if result.get("issues"):
            console.print("\n[bold]Issues:[/bold]")
            for issue in result["issues"]:
                console.print(f"  - {issue}")

    _run_async(_run())


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@cli.command()
def status():
    """Check server status and dependencies."""
    from .config import settings

    async def _run():
        from .ai.ollama_client import check_health
        ai_status = await check_health()

        table = Table(title="LeadGen Server Status")
        table.add_column("Component", style="cyan", width=22)
        table.add_column("Status")

        table.add_row("Server", "[green]leadgen-mcp v1.0.0[/green]")
        table.add_row("Database", settings.db_path)

        ai_ok = ai_status.get("status") == "ok" if isinstance(ai_status, dict) else False
        table.add_row(
            "AI Engine (Ollama)",
            f"[green]OK[/green] ({settings.ollama_model})" if ai_ok
            else f"[red]DOWN[/red] ({ai_status})",
        )
        table.add_row(
            "SMTP",
            f"[green]Configured[/green] ({settings.smtp_host})" if settings.smtp_user
            else "[yellow]Not configured[/yellow]",
        )
        table.add_row("Tracking URL", settings.tracking_base_url)
        table.add_row("Agency", settings.agency_name)

        console.print(table)

    _run_async(_run())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_leads_table(leads_data: list[dict], title: str = "Leads"):
    """Print a table of leads."""
    table = Table(title=title)
    table.add_column("ID", width=12, style="dim")
    table.add_column("Domain", width=25, style="cyan")
    table.add_column("Company", width=20)
    table.add_column("Source", width=14)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Signals", width=30)

    for lead in leads_data:
        score_val = lead.get("score", lead.get("_score_total", 0))
        if score_val and score_val >= 70:
            score_str = f"[bold green]{score_val}[/bold green]"
        elif score_val and score_val >= 40:
            score_str = f"[yellow]{score_val}[/yellow]"
        else:
            score_str = str(score_val or "-")

        signals = lead.get("signals", "[]")
        if isinstance(signals, str):
            import json
            try:
                signals = json.loads(signals)
            except Exception:
                signals = []
        signals_str = ", ".join(str(s) for s in (signals or []))[:30]

        table.add_row(
            lead.get("lead_id", lead.get("id", "?"))[:12],
            (lead.get("domain", "") or "")[:25],
            (lead.get("company_name", "") or "")[:20],
            lead.get("source_platform", lead.get("source", "?"))[:14],
            score_str,
            signals_str,
        )

    console.print(table)
    console.print(f"Total: {len(leads_data)}")


def _print_scan_section(title: str, data: dict):
    """Print a scan result section."""
    issues = data.get("issues", []) + data.get("missing_features", [])
    severity = data.get("severity", "info")
    color = {"critical": "red", "warning": "yellow"}.get(severity, "green")

    lines = [f"Severity: [{color}]{severity}[/{color}]"]
    lines.append(f"Issues: {len(issues)}")
    for issue in issues[:5]:
        if isinstance(issue, dict):
            lines.append(f"  - {issue.get('issue', issue.get('feature', str(issue)))}")
        else:
            lines.append(f"  - {issue}")
    if len(issues) > 5:
        lines.append(f"  ... and {len(issues) - 5} more")

    console.print(Panel("\n".join(lines), title=title, border_style=color))


def _print_cycle_stats(stats):
    """Print a formatted cycle stats summary."""
    console.print()
    console.print(Panel(
        "\n".join(stats.summary_lines()),
        title="Pipeline Cycle Summary",
        border_style="green" if stats.leads_discovered > 0 else "yellow",
    ))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
