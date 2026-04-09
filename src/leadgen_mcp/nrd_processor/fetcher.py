"""Fetch and parse newly registered domain lists from cenk/nrd GitHub repo.

The repo contains daily text files with one domain per line.
We clone or pull the repo, then parse domain lists for the requested
number of days, tracking which dates have already been ingested.
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from ..config import settings
from .models import NRD_SCHEMA_SQL

logger = logging.getLogger("leadgen.nrd.fetcher")

NRD_REPO_URL = "https://github.com/cenk/nrd.git"
NRD_DATA_DIR = "/opt/leadgen-mcp/data/nrd-repo"


async def _get_nrd_db() -> aiosqlite.Connection:
    """Get a connection to the shared DB with NRD tables initialized."""
    db_path = settings.db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(NRD_SCHEMA_SQL)
    await db.commit()
    return db


async def clone_or_pull_repo(data_dir: str = NRD_DATA_DIR) -> str:
    """Clone the cenk/nrd repo if not present, otherwise git pull.

    Returns the path to the repo directory.
    """
    repo_path = Path(data_dir)

    if (repo_path / ".git").exists():
        logger.info("NRD repo exists at %s, pulling latest...", data_dir)
        proc = await asyncio.create_subprocess_exec(
            "git", "pull", "--ff-only",
            cwd=str(repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("git pull failed: %s", stderr.decode().strip())
            # Try a fresh clone if pull fails
            logger.info("Attempting fresh clone...")
            import shutil
            shutil.rmtree(str(repo_path), ignore_errors=True)
            return await clone_or_pull_repo(data_dir)
        logger.info("git pull: %s", stdout.decode().strip())
    else:
        logger.info("Cloning NRD repo to %s ...", data_dir)
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth=1", NRD_REPO_URL, str(repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git clone failed: {stderr.decode().strip()}")
        logger.info("Cloned NRD repo successfully")

    return str(repo_path)


def _find_domain_files(repo_path: str, days: int = 60) -> dict[str, Path]:
    """Find domain list files for the last N days.

    The cenk/nrd repo stores files in various formats. We look for:
      - Files named like YYYY-MM-DD.txt or YYYY-MM-DD
      - Files inside date-named directories
      - Any .txt files with date patterns in the name

    Returns: dict mapping date string -> file path
    """
    repo = Path(repo_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    date_pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")
    found: dict[str, Path] = {}

    # Walk the repo looking for domain list files
    for path in sorted(repo.rglob("*")):
        if path.is_dir() or path.name.startswith("."):
            continue
        # Skip git internals
        if ".git" in path.parts:
            continue

        match = date_pattern.search(path.name)
        if not match:
            # Check parent directory name
            match = date_pattern.search(path.parent.name)
        if not match:
            continue

        date_str = match.group(1)
        if date_str >= cutoff_str:
            found[date_str] = path

    logger.info("Found %d domain files within last %d days", len(found), days)
    return found


def _parse_domain_file(filepath: Path) -> list[str]:
    """Parse a domain list file (one domain per line).

    Filters out comments, empty lines, and obvious junk.
    """
    domains = []
    try:
        text = filepath.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.warning("Failed to read %s: %s", filepath, e)
        return domains

    for line in text.splitlines():
        line = line.strip().lower()
        # Skip empty lines, comments, headers
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        # Basic domain validation: must have a dot, no spaces
        if "." not in line or " " in line or len(line) > 253:
            continue
        # Remove trailing dot if present (FQDN notation)
        if line.endswith("."):
            line = line[:-1]
        domains.append(line)

    return domains


def _extract_tld(domain: str) -> str:
    """Extract the TLD from a domain name."""
    parts = domain.rsplit(".", 1)
    return parts[-1] if len(parts) > 1 else ""


async def fetch_domains(
    days: int = 60,
    data_dir: str = NRD_DATA_DIR,
) -> dict[str, list[str]]:
    """Fetch and return domains grouped by date.

    Steps:
    1. Clone or pull the cenk/nrd repo
    2. Find domain files for the last N days
    3. Parse each file
    4. Return {date: [domain1, domain2, ...]}
    """
    repo_path = await clone_or_pull_repo(data_dir)
    date_files = _find_domain_files(repo_path, days)

    if not date_files:
        logger.warning("No domain files found for the last %d days", days)
        return {}

    result: dict[str, list[str]] = {}
    total = 0

    for date_str in sorted(date_files.keys(), reverse=True):
        filepath = date_files[date_str]
        domains = _parse_domain_file(filepath)
        if domains:
            result[date_str] = domains
            total += len(domains)
            logger.info("  %s: %d domains from %s", date_str, len(domains), filepath.name)

    logger.info("Total: %d domains across %d days", total, len(result))
    return result


async def ingest_domains_to_db(
    domains_by_date: dict[str, list[str]],
    skip_existing_dates: bool = True,
) -> dict[str, int]:
    """Insert domains into the nrd_domains table, skipping already-ingested dates.

    Returns: dict of {date: count_inserted}
    """
    db = await _get_nrd_db()
    stats: dict[str, int] = {}

    try:
        for date_str, domains in sorted(domains_by_date.items(), reverse=True):
            # Check if this date is already ingested
            if skip_existing_dates:
                row = await db.execute_fetchall(
                    "SELECT id FROM nrd_progress WHERE date = ? AND status IN ('done', 'in_progress')",
                    (date_str,),
                )
                if row:
                    logger.info("Skipping %s — already ingested", date_str)
                    stats[date_str] = 0
                    continue

            # Create progress entry
            await db.execute(
                """INSERT OR REPLACE INTO nrd_progress (date, total_domains, status, started_at)
                   VALUES (?, ?, 'in_progress', datetime('now'))""",
                (date_str, len(domains)),
            )

            # Batch insert domains
            inserted = 0
            batch_size = 500
            for i in range(0, len(domains), batch_size):
                batch = domains[i : i + batch_size]
                values = []
                for domain in batch:
                    tld = _extract_tld(domain)
                    values.append((domain, tld, date_str))

                await db.executemany(
                    """INSERT OR IGNORE INTO nrd_domains (domain, tld, registered_date)
                       VALUES (?, ?, ?)""",
                    values,
                )
                inserted += len(batch)

            await db.commit()

            # Update progress
            await db.execute(
                "UPDATE nrd_progress SET processed_count = ?, status = 'pending' WHERE date = ?",
                (inserted, date_str),
            )
            await db.commit()

            stats[date_str] = inserted
            logger.info("Ingested %d domains for %s", inserted, date_str)

    finally:
        await db.close()

    return stats
