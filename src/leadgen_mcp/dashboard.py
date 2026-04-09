"""Live terminal dashboard for monitoring the pipeline."""

import asyncio
import logging
from datetime import datetime, timezone

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .db.repository import (
    get_db,
    query_leads,
    get_email_analytics,
    close_db,
)

logger = logging.getLogger("leadgen.dashboard")


class Dashboard:
    """Live terminal dashboard showing pipeline stats, leads, and campaigns."""

    def __init__(self, scheduler=None, refresh_interval: float = 2.0):
        """
        Args:
            scheduler: Optional PipelineScheduler instance for live cycle info.
            refresh_interval: How often to refresh the dashboard (seconds).
        """
        self._scheduler = scheduler
        self._refresh = refresh_interval
        self._console = Console()
        self._running = True

    def _build_status_panel(self) -> Panel:
        """Pipeline status panel."""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Key", style="bold cyan", width=20)
        table.add_column("Value")

        if self._scheduler:
            table.add_row("Status",
                          "[green]RUNNING[/green]" if self._scheduler.is_running
                          else "[red]STOPPED[/red]")
            table.add_row("Started at", self._scheduler.started_at or "N/A")
            table.add_row("Cycles completed", str(self._scheduler.cycle_count))

            last = self._scheduler.last_stats
            if last:
                table.add_row("Last cycle", last.started_at)
                table.add_row("Last duration",
                              f"{last.duration_seconds:.1f}s")
                table.add_row("Last leads found", str(last.leads_discovered))
        else:
            table.add_row("Status", "[yellow]STANDALONE[/yellow]")
            table.add_row("Mode", "Dashboard only (no scheduler attached)")

        table.add_row("Current time",
                      datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

        return Panel(table, title="Pipeline Status", border_style="blue")

    async def _build_leads_panel(self) -> Panel:
        """Recent hot leads panel."""
        table = Table(box=None, padding=(0, 1))
        table.add_column("ID", style="dim", width=12)
        table.add_column("Domain", style="cyan", width=25)
        table.add_column("Company", width=20)
        table.add_column("Source", width=12)
        table.add_column("Score", justify="right", width=6)

        try:
            leads = await query_leads(min_score=40, limit=10)
            for lead in leads:
                score = lead.get("score", 0)
                if score >= 70:
                    score_str = f"[bold green]{score}[/bold green]"
                elif score >= 40:
                    score_str = f"[yellow]{score}[/yellow]"
                else:
                    score_str = str(score)

                table.add_row(
                    lead.get("id", "?"),
                    lead.get("domain", "N/A") or "N/A",
                    (lead.get("company_name", "") or "")[:20],
                    lead.get("source_platform", "?"),
                    score_str,
                )
        except Exception as e:
            table.add_row("Error", str(e), "", "", "")

        return Panel(table, title="Recent Hot Leads (score >= 40)",
                     border_style="green")

    async def _build_stats_panel(self) -> Panel:
        """Lead statistics panel."""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Metric", style="bold", width=22)
        table.add_column("Value", justify="right")

        try:
            all_leads = await query_leads(min_score=0, limit=10000)
            total = len(all_leads)

            hot = sum(1 for l in all_leads if l.get("score", 0) >= 70)
            warm = sum(1 for l in all_leads
                       if 40 <= l.get("score", 0) < 70)
            cold = sum(1 for l in all_leads if l.get("score", 0) < 40)

            # Count by source
            sources: dict[str, int] = {}
            for l in all_leads:
                src = l.get("source_platform", "unknown")
                sources[src] = sources.get(src, 0) + 1

            table.add_row("Total leads", str(total))
            table.add_row("[green]Hot (70+)[/green]", str(hot))
            table.add_row("[yellow]Warm (40-69)[/yellow]", str(warm))
            table.add_row("[dim]Cold (<40)[/dim]", str(cold))
            table.add_row("", "")

            for src, count in sorted(sources.items(),
                                     key=lambda x: x[1], reverse=True)[:8]:
                table.add_row(f"  {src}", str(count))
        except Exception as e:
            table.add_row("Error", str(e))

        return Panel(table, title="Lead Statistics", border_style="yellow")

    async def _build_email_panel(self) -> Panel:
        """Email analytics panel."""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Metric", style="bold", width=22)
        table.add_column("Value", justify="right")

        try:
            analytics = await get_email_analytics(days=30)
            total_sent = analytics.get("total_sent", 0) or 0
            total_opened = analytics.get("total_opened", 0) or 0
            total_clicked = analytics.get("total_clicked", 0) or 0
            total_bounced = analytics.get("total_bounced", 0) or 0

            table.add_row("Emails sent (30d)", str(total_sent))
            table.add_row("Opened", str(total_opened))
            table.add_row("Clicked", str(total_clicked))
            table.add_row("Bounced", str(total_bounced))
            table.add_row(
                "Open rate",
                f"{total_opened / total_sent * 100:.1f}%" if total_sent else "N/A",
            )
            table.add_row(
                "Click rate",
                f"{total_clicked / total_sent * 100:.1f}%" if total_sent else "N/A",
            )
        except Exception as e:
            table.add_row("Error", str(e))

        return Panel(table, title="Email Stats (30 days)",
                     border_style="magenta")

    async def _build_cycle_history_panel(self) -> Panel:
        """Recent cycle history panel."""
        table = Table(box=None, padding=(0, 1))
        table.add_column("#", width=4, justify="right")
        table.add_column("Started", width=20)
        table.add_column("Duration", width=10, justify="right")
        table.add_column("Leads", width=6, justify="right")
        table.add_column("Scanned", width=8, justify="right")
        table.add_column("Emails", width=7, justify="right")

        if self._scheduler and self._scheduler.history:
            for i, cycle in enumerate(reversed(self._scheduler.history[-10:]),
                                      start=1):
                table.add_row(
                    str(self._scheduler.cycle_count - i + 1),
                    cycle.started_at[:19] if cycle.started_at else "?",
                    f"{cycle.duration_seconds:.0f}s",
                    str(cycle.leads_discovered),
                    f"{cycle.scan_successes}/{cycle.websites_scanned}",
                    str(cycle.emails_generated),
                )
        else:
            table.add_row("-", "No cycles yet", "", "", "", "")

        return Panel(table, title="Cycle History", border_style="cyan")

    async def _build_layout(self) -> Layout:
        """Build the full dashboard layout."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=1),
            Layout(name="body"),
            Layout(name="footer", size=1),
        )

        layout["header"].update(
            Text(
                " LeadGen Pipeline Dashboard ",
                style="bold white on blue",
                justify="center",
            )
        )

        layout["body"].split_row(
            Layout(name="left"),
            Layout(name="right"),
        )

        # Left side: status + leads
        status_panel = self._build_status_panel()
        leads_panel = await self._build_leads_panel()
        history_panel = await self._build_cycle_history_panel()

        layout["left"].split_column(
            Layout(status_panel, name="status", size=12),
            Layout(leads_panel, name="leads"),
            Layout(history_panel, name="history", size=14),
        )

        # Right side: stats + email
        stats_panel = await self._build_stats_panel()
        email_panel = await self._build_email_panel()

        layout["right"].split_column(
            Layout(stats_panel, name="stats"),
            Layout(email_panel, name="email"),
        )

        layout["footer"].update(
            Text(
                " Press Ctrl+C to exit ",
                style="dim",
                justify="center",
            )
        )

        return layout

    async def run(self):
        """Show live dashboard with stats, recent leads, campaign progress."""
        await get_db()

        with Live(
            await self._build_layout(),
            console=self._console,
            refresh_per_second=1,
            screen=True,
        ) as live:
            try:
                while self._running:
                    layout = await self._build_layout()
                    live.update(layout)
                    await asyncio.sleep(self._refresh)
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass

        await close_db()

    def stop(self):
        self._running = False
