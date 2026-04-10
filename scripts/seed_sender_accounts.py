#!/usr/bin/env python3
"""Seed all sender accounts into PostgreSQL.

Creates 5 email accounts per domain (sales, info, hello, team, support)
with proper display names and pool assignments.

Usage:
    DATABASE_URL=postgresql://... python3 scripts/seed_sender_accounts.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

DOMAINS_FILE = os.path.join(os.path.dirname(__file__), "domains.txt")
DEFAULT_PASSWORD = "Nubo@2026!Secure"
SMTP_HOST = "mail.nubo.email"
SMTP_PORT = 587
IMAP_HOST = "mail.nubo.email"
IMAP_PORT = 993

# Account prefixes and display names
ACCOUNTS = [
    ("sales", "Sales Team"),
    ("info", "Info"),
    ("hello", "Hello"),
    ("team", "Team"),
    ("support", "Support"),
]

# Domain → vertical mapping for display names
DOMAIN_VERTICALS = {
    "hostingduty": "HostingDuty",
    "emailsify": "Emailsify",
    "postly": "Postly",
    "netemailsify": "NetEmailsify",
    "netpostio": "NetPostio",
    "buttonbada": "ButtonBada",
    "digipins": "DigiPins",
    "kaizeninfosys": "Kaizen Infosys",
    "onewarehouse": "OneWarehouse",
    "0xlabs": "0xLabs",
    "puneix": "Puneix",
    "cli.coffee": "CLI.coffee",
    "marketx": "MarketX",
    "mktx": "MKTX",
    "tezcms": "TezCMS",
    "digitalgappa": "DigitalGappa",
    "chandorkartechnologies": "Chandorkar Technologies",
    "chandorkarlabs": "Chandorkar Labs",
    "streesakhi": "StreeSakhi",
    "nebulaproject": "Nebula Project",
    "logiclane": "LogicLane",
    "nubopay": "NuboPay",
    "uid": "UID",
    "nubo": "Nubo",
    "cybercartel": "CyberCartel",
    "tez": "Tez",
    "rotarycms": "RotaryCMS",
}


def get_brand_name(domain: str) -> str:
    """Extract brand name from domain."""
    name = domain.split(".")[0]
    return DOMAIN_VERTICALS.get(name, name.title())


async def main():
    from leadgen_mcp.db.pg_repository import get_pool, add_sender_account

    pool = await get_pool()

    with open(DOMAINS_FILE) as f:
        domains = [line.strip() for line in f if line.strip()]

    total = 0
    created = 0

    # Distribute domains across pools for warmup staggering
    # First 12 domains = Pool A (warming first)
    # Next 12 = Pool B (warming second wave, start day 0 but delayed start)
    # Last 12 = Pool C (warming third wave)

    for i, domain in enumerate(domains):
        brand = get_brand_name(domain)

        for prefix, role in ACCOUNTS:
            email = f"{prefix}@{domain}"
            display_name = f"{role} - {brand}"

            try:
                result = await add_sender_account(
                    email=email,
                    domain=domain,
                    display_name=display_name,
                    smtp_user=email,
                    smtp_password=DEFAULT_PASSWORD,
                    smtp_host=SMTP_HOST,
                    smtp_port=SMTP_PORT,
                    imap_host=IMAP_HOST,
                    imap_port=IMAP_PORT,
                )
                created += 1
                print(f"  [{created:>3}] {email:>45} | {display_name}")
            except Exception as e:
                print(f"  SKIP {email}: {e}")

            total += 1

    await pool.close()

    print(f"\n=== Done: {created}/{total} accounts created ===")
    print(f"All accounts start in 'warming' pool with 3/day quota")
    print(f"Run warmup daemon to start building reputation")


if __name__ == "__main__":
    asyncio.run(main())
