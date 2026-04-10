"""Scheduler for running the pipeline on a configurable interval.

Supports graceful shutdown via SIGINT/SIGTERM, tracks cycle history,
and spawns warmup daemon + IMAP poller as background tasks.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone

from .pipeline import LeadGenPipeline, PipelineConfig, CycleStats
from .config import settings

logger = logging.getLogger("leadgen.scheduler")


class PipelineScheduler:
    """Runs the pipeline on a schedule, handles graceful shutdown."""

    def __init__(self, pipeline: LeadGenPipeline):
        self._pipeline = pipeline
        self._running = True
        self._cycle_count = 0
        self._last_stats: CycleStats | None = None
        self._history: list[CycleStats] = []
        self._started_at: str = ""
        self._background_tasks: list[asyncio.Task] = []

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def last_stats(self) -> CycleStats | None:
        return self._last_stats

    @property
    def history(self) -> list[CycleStats]:
        return self._history

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def started_at(self) -> str:
        return self._started_at

    def _install_signal_handlers(self):
        """Install signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        def _handle_stop(sig):
            logger.info("Received signal %s — shutting down gracefully...", sig.name)
            self._running = False

        if sys.platform == "win32":
            try:
                loop.add_signal_handler(signal.SIGINT, _handle_stop, signal.SIGINT)
            except NotImplementedError:
                signal.signal(signal.SIGINT, lambda s, f: self.stop())
        else:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _handle_stop, sig)

    async def _start_background_services(self):
        """Start warmup daemon and IMAP poller if PostgreSQL is configured."""
        if not settings.database_url:
            logger.info("No DATABASE_URL — skipping warmup and IMAP daemons")
            return

        # Start warmup daemon
        if settings.warmup_enabled:
            try:
                from .warmup.daemon import WarmupDaemon
                warmup = WarmupDaemon()
                task = asyncio.create_task(warmup.run_forever())
                self._background_tasks.append(task)
                logger.info("Warmup daemon started (cycle every %.1fh)", settings.warmup_cycle_hours)
            except Exception as e:
                logger.warning("Failed to start warmup daemon: %s", e)

        # Start IMAP poller
        try:
            from .imap_aggregate.poller import IMAPAggregator
            imap = IMAPAggregator()
            task = asyncio.create_task(imap.run_forever())
            self._background_tasks.append(task)
            logger.info("IMAP aggregator started (poll every %ds)", settings.imap_poll_interval)
        except Exception as e:
            logger.warning("Failed to start IMAP aggregator: %s", e)

        # Start queue worker (processes enrich/score/email_generate/email_send)
        try:
            from .queue import create_default_worker
            worker = create_default_worker()
            task = asyncio.create_task(worker.run_forever())
            self._background_tasks.append(task)
            logger.info("Queue worker started")
        except Exception as e:
            logger.warning("Failed to start queue worker: %s", e)

    async def _stop_background_services(self):
        """Stop all background tasks."""
        for task in self._background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._background_tasks.clear()

    async def run_forever(self):
        """Run pipeline cycles indefinitely until stopped."""
        self._started_at = datetime.now(timezone.utc).isoformat()
        interval = self._pipeline.config.cycle_interval_hours

        logger.info(
            "Pipeline scheduler started. Cycle interval: %.1f hours. "
            "Dry run: %s. Platforms: %s. DB: %s",
            interval,
            self._pipeline.config.dry_run,
            ", ".join(self._pipeline.config.platforms),
            "postgresql" if settings.database_url else "sqlite",
        )

        try:
            self._install_signal_handlers()
        except Exception:
            logger.debug("Could not install signal handlers — "
                         "use Ctrl+C for graceful shutdown")

        # Start background services
        await self._start_background_services()

        while self._running:
            self._cycle_count += 1
            cycle_num = self._cycle_count

            logger.info(
                "=== Cycle %d starting at %s ===",
                cycle_num,
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            )

            try:
                stats = await self._pipeline.run_full_cycle()
                self._last_stats = stats
                self._history.append(stats)
                if len(self._history) > 50:
                    self._history = self._history[-50:]
                logger.info("=== Cycle %d complete ===", cycle_num)
            except Exception as e:
                logger.error(
                    "=== Cycle %d FAILED: %s ===", cycle_num, e, exc_info=True
                )

            if not self._running:
                break

            wait_seconds = interval * 3600
            logger.info(
                "Next cycle in %.1f hours. Waiting...", interval,
            )
            elapsed = 0.0
            while elapsed < wait_seconds and self._running:
                await asyncio.sleep(min(1.0, wait_seconds - elapsed))
                elapsed += 1.0

        logger.info(
            "Scheduler stopped after %d cycles. Cleaning up...", self._cycle_count
        )
        await self._stop_background_services()
        await self._close_db()
        logger.info("Shutdown complete.")

    async def _close_db(self):
        """Close database connections."""
        if settings.database_url:
            from .db.pg_repository import close_db
        else:
            from .db.repository import close_db
        await close_db()

    def stop(self):
        """Signal the scheduler to stop after the current cycle."""
        self._running = False

    async def run_single(self) -> CycleStats:
        """Run a single pipeline cycle and return stats."""
        await self._pipeline._ensure_db()
        stats = await self._pipeline.run_full_cycle()
        self._last_stats = stats
        self._cycle_count += 1
        await self._close_db()
        return stats
