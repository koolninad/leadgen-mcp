#!/usr/bin/env python3
"""Create social media accounts using our Stalwart email addresses.

Uses Patchright (undetected Playwright) for browser automation.
Reads verification emails from Stalwart via IMAP.

Platforms: Reddit, Twitter/X, LinkedIn
Usage:
    PYTHONPATH=./src python3 scripts/create_social_accounts.py reddit --count 10
    PYTHONPATH=./src python3 scripts/create_social_accounts.py twitter --count 5
    PYTHONPATH=./src python3 scripts/create_social_accounts.py linkedin --count 3
"""

import asyncio
import csv
import email as email_lib
import imaplib
import json
import logging
import os
import random
import re
import string
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("social_creator")

# Password for all social accounts
SOCIAL_PASSWORD = "CT@2026!Social"
IMAP_HOST = "mail.nubo.email"
IMAP_PORT = 993
EMAIL_PASSWORD = "Nubo@2026!Secure"

# Account plan — email → (platform, username/handle)
REDDIT_ACCOUNTS = [
    ("info@chandorkartechnologies.us", "chandorkar_tech"),
    ("info@kaizeninfosys.com", "kaizen_devops"),
    ("info@digitalgappa.com", "digitalgappa_dev"),
    ("info@puneix.com", "puneix_builder"),
    ("info@emailsify.com", "emailsify_io"),
    ("info@hostingduty.pro", "hosting_guru_pro"),
    ("info@0xlabs.app", "oxlabs_dev"),
    ("info@marketx.club", "marketx_growth"),
    ("info@cli.coffee", "cli_coffee_dev"),
    ("info@tezcms.dev", "tezcms_builder"),
]

TWITTER_ACCOUNTS = [
    ("info@chandorkartechnologies.us", "ChandorkarTech"),
    ("info@hostingduty.pro", "HostingDutyPro"),
    ("info@0xlabs.app", "OxLabsApp"),
    ("info@digitalgappa.com", "DigitalGappaDev"),
    ("info@kaizeninfosys.com", "KaizenInfoDev"),
]

LINKEDIN_ACCOUNTS = [
    # LinkedIn needs REAL names — use company pages or real people
    ("info@chandorkartechnologies.us", "Chandorkar Technologies", "Company"),
    ("info@hostingduty.pro", "HostingDuty", "Company"),
    ("info@0xlabs.app", "0xLabs", "Company"),
]

OUTPUT_FILE = "data/social_accounts.csv"


def get_verification_code(email_addr: str, platform: str, timeout: int = 120) -> str | None:
    """Check IMAP for verification email and extract code/link."""
    logger.info(f"  Waiting for verification email at {email_addr}...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            conn.login(email_addr, EMAIL_PASSWORD)
            conn.select("INBOX")

            # Search for recent unread emails
            _, msg_nums = conn.search(None, "UNSEEN")
            if not msg_nums[0]:
                conn.logout()
                time.sleep(5)
                continue

            for num in reversed(msg_nums[0].split()):
                _, data = conn.fetch(num, "(RFC822)")
                if not data or not data[0]:
                    continue

                msg = email_lib.message_from_bytes(data[0][1])
                subject = msg.get("Subject", "").lower()
                from_addr = msg.get("From", "").lower()
                body = ""

                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode("utf-8", errors="replace")
                                break
                        elif part.get_content_type() == "text/html":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode("utf-8", errors="replace")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")

                # Reddit verification
                if platform == "reddit" and ("reddit" in from_addr or "reddit" in subject):
                    # Look for verification link
                    link_match = re.search(r'https://www\.reddit\.com/verification/[^\s"<]+', body)
                    if link_match:
                        conn.logout()
                        return link_match.group(0)
                    # Look for code
                    code_match = re.search(r'(\d{6})', body)
                    if code_match:
                        conn.logout()
                        return code_match.group(1)

                # Twitter verification
                if platform == "twitter" and ("twitter" in from_addr or "x.com" in from_addr or "verify" in subject):
                    code_match = re.search(r'(\d{6,8})', body)
                    if code_match:
                        conn.logout()
                        return code_match.group(1)
                    link_match = re.search(r'https://[^\s"<]*verify[^\s"<]*', body)
                    if link_match:
                        conn.logout()
                        return link_match.group(0)

                # LinkedIn verification
                if platform == "linkedin" and ("linkedin" in from_addr or "verify" in subject):
                    code_match = re.search(r'(\d{6})', body)
                    if code_match:
                        conn.logout()
                        return code_match.group(1)

            conn.logout()

        except Exception as e:
            logger.debug(f"  IMAP check failed: {e}")

        time.sleep(5)

    return None


def save_account(platform: str, email: str, username: str, password: str):
    """Save account to CSV."""
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    file_exists = os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a") as f:
        if not file_exists:
            f.write("platform,email,username,password,created_at\n")
        f.write(f"{platform},{email},{username},{password},{time.strftime('%Y-%m-%d %H:%M:%S')}\n")


async def create_reddit_account(email: str, username: str) -> bool:
    """Create a Reddit account using Patchright."""
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        from playwright.async_api import async_playwright

    logger.info(f"Creating Reddit: {username} ({email})")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            )
            page = await context.new_page()

            # Go to Reddit signup
            await page.goto("https://www.reddit.com/register/", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Fill email
            email_input = page.locator('input[name="email"], #regEmail')
            await email_input.fill(email)
            await asyncio.sleep(1)

            # Click continue/next
            continue_btn = page.locator('button:has-text("Continue"), button:has-text("Sign Up"), button[type="submit"]').first
            await continue_btn.click()
            await asyncio.sleep(3)

            # Fill username
            username_input = page.locator('input[name="username"], #regUsername')
            await username_input.fill(username)
            await asyncio.sleep(1)

            # Fill password
            password_input = page.locator('input[name="password"], #regPassword')
            await password_input.fill(SOCIAL_PASSWORD)
            await asyncio.sleep(1)

            # Submit
            submit_btn = page.locator('button:has-text("Sign Up"), button:has-text("Continue"), button[type="submit"]').first
            await submit_btn.click()
            await asyncio.sleep(5)

            # Check for captcha or verification
            page_content = await page.content()
            if "captcha" in page_content.lower() or "recaptcha" in page_content.lower():
                logger.warning(f"  CAPTCHA detected for {username} — need manual intervention")
                await browser.close()
                return False

            # Wait for email verification
            code = get_verification_code(email, "reddit", timeout=60)
            if code:
                if code.startswith("http"):
                    await page.goto(code, timeout=15000)
                else:
                    # Enter code
                    code_input = page.locator('input[name="code"], input[type="text"]').first
                    await code_input.fill(code)
                    verify_btn = page.locator('button:has-text("Verify"), button[type="submit"]').first
                    await verify_btn.click()
                    await asyncio.sleep(3)

                logger.info(f"  Reddit account created: {username}")
                save_account("reddit", email, username, SOCIAL_PASSWORD)
                await browser.close()
                return True
            else:
                logger.warning(f"  No verification email received for {username}")

            await browser.close()

    except Exception as e:
        logger.error(f"  Reddit creation failed for {username}: {e}")

    return False


async def create_twitter_account(email: str, handle: str) -> bool:
    """Create a Twitter/X account using Patchright."""
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        from playwright.async_api import async_playwright

    logger.info(f"Creating Twitter: @{handle} ({email})")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            )
            page = await context.new_page()

            await page.goto("https://x.com/i/flow/signup", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)

            # Twitter signup flow is multi-step
            # Step 1: Name
            name_input = page.locator('input[name="name"]').first
            await name_input.fill(handle)
            await asyncio.sleep(1)

            # Step 2: Email
            email_input = page.locator('input[name="email"]').first
            await email_input.fill(email)
            await asyncio.sleep(1)

            # Click Next
            next_btn = page.locator('button:has-text("Next"), [role="button"]:has-text("Next")').first
            await next_btn.click()
            await asyncio.sleep(3)

            # Twitter usually asks for phone or shows captcha
            page_content = await page.content()
            if "phone" in page_content.lower():
                logger.warning(f"  Twitter requires phone number for {handle}")
                await browser.close()
                return False

            # Enter verification code
            code = get_verification_code(email, "twitter", timeout=90)
            if code:
                code_input = page.locator('input[name="verfication_code"], input[type="text"]').first
                await code_input.fill(code)
                next_btn = page.locator('button:has-text("Next")').first
                await next_btn.click()
                await asyncio.sleep(2)

                # Set password
                pw_input = page.locator('input[name="password"], input[type="password"]').first
                await pw_input.fill(SOCIAL_PASSWORD)
                next_btn = page.locator('button:has-text("Next"), button:has-text("Sign up")').first
                await next_btn.click()
                await asyncio.sleep(3)

                logger.info(f"  Twitter account created: @{handle}")
                save_account("twitter", email, handle, SOCIAL_PASSWORD)
                await browser.close()
                return True

            logger.warning(f"  No Twitter verification for {handle}")
            await browser.close()

    except Exception as e:
        logger.error(f"  Twitter creation failed for {handle}: {e}")

    return False


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Create social media accounts")
    parser.add_argument("platform", choices=["reddit", "twitter", "linkedin", "all"])
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--start", type=int, default=0, help="Start index")
    args = parser.parse_args()

    results = {"created": 0, "failed": 0, "captcha": 0}

    if args.platform in ("reddit", "all"):
        accounts = REDDIT_ACCOUNTS[args.start:args.start + args.count]
        logger.info(f"\n=== Creating {len(accounts)} Reddit accounts ===")
        for email, username in accounts:
            ok = await create_reddit_account(email, username)
            results["created" if ok else "failed"] += 1
            await asyncio.sleep(random.randint(30, 60))  # Delay between accounts

    if args.platform in ("twitter", "all"):
        accounts = TWITTER_ACCOUNTS[args.start:args.start + args.count]
        logger.info(f"\n=== Creating {len(accounts)} Twitter accounts ===")
        for email, handle in accounts:
            ok = await create_twitter_account(email, handle)
            results["created" if ok else "failed"] += 1
            await asyncio.sleep(random.randint(30, 60))

    if args.platform in ("linkedin", "all"):
        logger.info(f"\n=== LinkedIn accounts require manual creation ===")
        logger.info("LinkedIn aggressively bans automated signups.")
        logger.info("Create these manually and add creds to GrowChief:")
        for email, name, acct_type in LINKEDIN_ACCOUNTS:
            logger.info(f"  {email} -> {name} ({acct_type})")
        logger.info("\nOnce created, run:")
        logger.info("  Add to /opt/growchief config with the credentials")

    logger.info(f"\n=== RESULTS: Created={results['created']} Failed={results['failed']} ===")
    if os.path.exists(OUTPUT_FILE):
        logger.info(f"Accounts saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
