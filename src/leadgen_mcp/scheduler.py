"""Scheduler for running the pipeline on a configurable interval.

Supports graceful shutdown via SIGINT/SIGTERM and tracks cycle history.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone

from .pipeline import LeadGenPipeline, PipelineConfig, CycleStats
from .db.repository import close_db

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

        # On Windows, only SIGINT is supported via add_signal_handler;
        # SIGTERM and SIGBREAK are handled differently.
        if sys.platform == "win32":
            # On Windows, SIGINT is handled by default (KeyboardInterrupt),
            # but we also try to register handlers for clean async shutdown.
            try:
                loop.add_signal_handler(signal.SIGINT, _handle_stop, signal.SIGINT)
            except NotImplementedError:
                # Fallback: Python on Windows doesn't always support add_signal_handler
                signal.signal(signal.SIGINT, lambda s, f: self.stop())
        else:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _handle_stop, sig)

    async def run_forever(self):
        """Run pipeline cycles indefinitely until stopped."""
        self._started_at = datetime.now(timezone.utc).isoformat()
        interval = self._pipeline.config.cycle_interval_hours

        logger.info(
            "Pipeline scheduler started. Cycle interval: %.1f hours. "
            "Dry run: %s. Platforms: %s",
            interval,
            self._pipeline.config.dry_run,
            ", ".join(self._pipeline.config.platforms),
        )

        try:
            self._install_signal_handlers()
        except Exception:
            logger.debug("Could not install signal handlers — "
                         "use Ctrl+C for graceful shutdown")

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
                # Keep only last 50 cycle stats in memory
                if len(self._history) > 50:
                    self._history = self._history[-50:]
                logger.info("=== Cycle %d complete ===", cycle_num)
            except Exception as e:
                logger.error(
                    "=== Cycle %d FAILED: %s ===", cycle_num, e, exc_info=True
                )

            if not self._running:
                break

            # Wait for next cycle, checking every second so we can respond
            # to shutdown signals promptly
            wait_seconds = interval * 3600
            logger.info(
                "Next cycle in %.1f hours (at %s). Waiting...",
                interval,
                datetime.now(timezone.utc).strftime("%H:%M:%S"),
            )
            elapsed = 0.0
            while elapsed < wait_seconds and self._running:
                await asyncio.sleep(min(1.0, wait_seconds - elapsed))
                elapsed += 1.0

        logger.info(
            "Scheduler stopped after %d cycles. Cleaning up...", self._cycle_count
        )
        await close_db()
        logger.info("Shutdown complete.")

    def stop(self):
        """Signal the scheduler to stop after the current cycle."""
        self._running = False

    async def run_single(self) -> CycleStats:
        """Run a single pipeline cycle and return stats."""
        from .db.repository import get_db
        await get_db()
        stats = await self._pipeline.run_full_cycle()
        self._last_stats = stats
        self._cycle_count += 1
        await close_db()
        return stats
