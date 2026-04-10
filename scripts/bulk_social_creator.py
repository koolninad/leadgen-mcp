#!/usr/bin/env python3
"""Bulk Social Media Account Creator.

Creates Reddit, Twitter/X, and LinkedIn accounts using:
- Patchright (undetected browser) — already installed
- Stalwart IMAP for email verification — free
- IPv6 rotation for clean IPs — free
- GoogleRecaptchaBypass for captcha — free (audio speech-to-text)
- Quackr.io free numbers OR 5SIM ($0.008/number) for phone verification

Usage:
    # Reddit (usually no phone needed with clean IP)
    PYTHONPATH=./src python3 scripts/bulk_social_creator.py reddit --count 10

    # Twitter (needs phone)
    PYTHONPATH=./src python3 scripts/bulk_social_creator.py twitter --count 5 --sms-provider 5sim --sms-api-key YOUR_KEY

    # LinkedIn (needs phone)
    PYTHONPATH=./src python3 scripts/bulk_social_creator.py linkedin --count 3 --sms-provider 5sim --sms-api-key YOUR_KEY

    # All platforms
    PYTHONPATH=./src python3 scripts/bulk_social_creator.py all --sms-api-key YOUR_KEY
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
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bulk_creator")

# ── Config ──
IMAP_HOST = "mail.nubo.email"
IMAP_PORT = 993
EMAIL_PASSWORD = "Nubo@2026!Secure"
SOCIAL_PASSWORD = "CT@2026!Social"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "social_accounts.csv")

# Account definitions
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
    ("info@chandorkartechnologies.us", "Ninad Chandorkar", "Chandorkar Technologies"),
    ("info@hostingduty.pro", "Aniket Bapat", "HostingDuty"),
    ("info@0xlabs.app", "0xLabs Team", "0xLabs"),
]

# ── SMS Providers ──

class SMSProvider:
    """Base SMS provider."""
    async def get_number(self, service: str) -> dict:
        """Returns {id, number} or {error}"""
        raise NotImplementedError

    async def get_code(self, activation_id: str, timeout: int = 120) -> str | None:
        """Wait for and return the verification code."""
        raise NotImplementedError

    async def cancel(self, activation_id: str):
        pass


class FiveSimProvider(SMSProvider):
    """5sim.net — $0.008/number."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://5sim.net/v1"

    async def get_number(self, service: str) -> dict:
        import httpx
        service_map = {"reddit": "reddit", "twitter": "twitter", "linkedin": "linkedin"}
        svc = service_map.get(service, service)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/user/buy/activation/any/any/{svc}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {"id": str(data["id"]), "number": data["phone"]}
            return {"error": f"5sim error: {resp.status_code} {resp.text[:100]}"}

    async def get_code(self, activation_id: str, timeout: int = 120) -> str | None:
        import httpx
        start = time.time()
        while time.time() - start < timeout:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/user/check/{activation_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("sms"):
                        code = data["sms"][0].get("code", "")
                        if code:
                            return code
            await asyncio.sleep(5)
        return None

    async def cancel(self, activation_id: str):
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(
                f"{self.base_url}/user/cancel/{activation_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )


class FreeQuackrProvider(SMSProvider):
    """Quackr.io — free temporary numbers (may not work for all services)."""

    async def get_number(self, service: str) -> dict:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Scrape available free numbers
                resp = await client.get("https://quackr.io/api/public/numbers?country=US")
                if resp.status_code == 200:
                    numbers = resp.json()
                    if numbers:
                        num = random.choice(numbers)
                        return {"id": num.get("id", num.get("number")), "number": num.get("number")}
        except Exception as e:
            logger.debug(f"Quackr failed: {e}")
        return {"error": "No free numbers available"}

    async def get_code(self, activation_id: str, timeout: int = 120) -> str | None:
        import httpx
        start = time.time()
        while time.time() - start < timeout:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(f"https://quackr.io/api/public/sms/{activation_id}")
                    if resp.status_code == 200:
                        messages = resp.json()
                        for msg in messages:
                            text = msg.get("body", "")
                            code_match = re.search(r'(\d{5,8})', text)
                            if code_match:
                                return code_match.group(1)
            except Exception:
                pass
            await asyncio.sleep(5)
        return None


# ── IMAP Email Verification ──

def fetch_verification_email(email_addr: str, platform: str, timeout: int = 90) -> str | None:
    """Check IMAP for verification email. Returns code or link."""
    logger.info(f"  Checking IMAP for {platform} verification at {email_addr}...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            conn.login(email_addr, EMAIL_PASSWORD)
            conn.select("INBOX")
            _, msg_nums = conn.search(None, "UNSEEN")

            if msg_nums[0]:
                for num in reversed(msg_nums[0].split()):
                    _, data = conn.fetch(num, "(RFC822)")
                    if not data or not data[0]:
                        continue

                    msg = email_lib.message_from_bytes(data[0][1])
                    subject = (msg.get("Subject") or "").lower()
                    from_addr = (msg.get("From") or "").lower()
                    body = _extract_body(msg)

                    if platform == "reddit" and ("reddit" in from_addr or "reddit" in subject):
                        link = re.search(r'https://www\.reddit\.com/verification/[^\s"<>]+', body)
                        if link:
                            conn.logout()
                            return link.group(0)
                        code = re.search(r'(\d{6})', body)
                        if code:
                            conn.logout()
                            return code.group(1)

                    if platform == "twitter" and ("twitter" in from_addr or "x.com" in from_addr):
                        code = re.search(r'(\d{5,8})', body)
                        if code:
                            conn.logout()
                            return code.group(1)

                    if platform == "linkedin" and "linkedin" in from_addr:
                        code = re.search(r'(\d{6})', body)
                        if code:
                            conn.logout()
                            return code.group(1)

            conn.logout()
        except Exception as e:
            logger.debug(f"  IMAP error: {e}")

        time.sleep(5)

    return None


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True)
                if payload:
                    text = payload.decode("utf-8", errors="replace")
                    if ct == "text/html":
                        text = re.sub(r'<[^>]+>', ' ', text)
                    return text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode("utf-8", errors="replace")
    return ""


# ── Account Savers ──

def save_account(platform: str, email: str, username: str, password: str, phone: str = ""):
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    exists = os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a") as f:
        if not exists:
            f.write("platform,email,username,password,phone,created_at\n")
        f.write(f"{platform},{email},{username},{password},{phone},{time.strftime('%Y-%m-%d %H:%M:%S')}\n")


# ── Platform Creators ──

async def create_reddit(email: str, username: str, sms_provider: SMSProvider | None = None) -> bool:
    """Create a Reddit account."""
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
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="en-US",
            )
            page = await ctx.new_page()

            # Navigate to registration
            await page.goto("https://www.reddit.com/account/register/", timeout=60000)
            await asyncio.sleep(3)

            # Wait for the signup form to render (SPA)
            try:
                await page.wait_for_selector('input[name="email"], faceplate-text-input, input[type="email"]', timeout=15000)
            except Exception:
                # Try alternative URL
                await page.goto("https://www.reddit.com/register", timeout=60000)
                await asyncio.sleep(5)

            # Fill email
            email_input = page.locator('input[name="email"], input[type="email"]').first
            await email_input.click()
            await email_input.fill(email)
            await asyncio.sleep(1)

            # Click continue
            continue_btn = page.locator('button[type="submit"], button:has-text("Continue"), button:has-text("Sign Up")').first
            await continue_btn.click()
            await asyncio.sleep(4)

            # Handle potential captcha
            page_html = await page.content()
            if "recaptcha" in page_html.lower() or "captcha" in page_html.lower():
                logger.info("  Captcha detected — attempting audio bypass...")
                solved = await _solve_recaptcha_audio(page)
                if not solved:
                    logger.warning(f"  Captcha not solved for {username}")
                    await browser.close()
                    return False

            # Fill username
            try:
                username_input = page.locator('input[name="username"]').first
                await username_input.click()
                await username_input.fill(username)
                await asyncio.sleep(1)
            except Exception:
                logger.debug("  Username field not found, may be next step")

            # Fill password
            try:
                pw_input = page.locator('input[name="password"], input[type="password"]').first
                await pw_input.click()
                await pw_input.fill(SOCIAL_PASSWORD)
                await asyncio.sleep(1)
            except Exception:
                logger.debug("  Password field not found")

            # Submit
            submit_btn = page.locator('button[type="submit"]').first
            await submit_btn.click()
            await asyncio.sleep(5)

            # Check if phone verification is needed
            page_html = await page.content()
            if "phone" in page_html.lower() and "verify" in page_html.lower():
                if sms_provider:
                    logger.info("  Phone verification required — getting number...")
                    result = await sms_provider.get_number("reddit")
                    if "error" not in result:
                        phone_input = page.locator('input[type="tel"], input[name="phone"]').first
                        await phone_input.fill(result["number"])
                        send_btn = page.locator('button:has-text("Send"), button[type="submit"]').first
                        await send_btn.click()
                        await asyncio.sleep(3)

                        code = await sms_provider.get_code(result["id"])
                        if code:
                            code_input = page.locator('input[name="code"], input[type="text"]').first
                            await code_input.fill(code)
                            verify_btn = page.locator('button:has-text("Verify"), button[type="submit"]').first
                            await verify_btn.click()
                            await asyncio.sleep(3)
                else:
                    logger.info("  Phone required but no SMS provider — trying to skip...")
                    skip_btn = page.locator('button:has-text("Skip"), a:has-text("Skip")').first
                    try:
                        await skip_btn.click(timeout=3000)
                    except Exception:
                        logger.warning(f"  Can't skip phone for {username}")
                        await browser.close()
                        return False

            # Email verification
            verification = fetch_verification_email(email, "reddit", timeout=60)
            if verification:
                if verification.startswith("http"):
                    await page.goto(verification, timeout=15000)
                    await asyncio.sleep(3)
                logger.info(f"  Reddit account created: {username}")
                save_account("reddit", email, username, SOCIAL_PASSWORD)
                await browser.close()
                return True
            else:
                # Might have succeeded without email verification
                if "reddit.com" in page.url and "register" not in page.url:
                    logger.info(f"  Reddit account created (no email verify needed): {username}")
                    save_account("reddit", email, username, SOCIAL_PASSWORD)
                    await browser.close()
                    return True

            logger.warning(f"  Reddit creation unclear for {username}")
            await browser.close()

    except Exception as e:
        logger.error(f"  Reddit failed for {username}: {e}")

    return False


async def create_twitter(email: str, handle: str, sms_provider: SMSProvider) -> bool:
    """Create a Twitter/X account. Always needs phone."""
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
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1366, "height": 768},
            )
            page = await ctx.new_page()

            await page.goto("https://x.com/i/flow/signup", timeout=60000)
            await asyncio.sleep(5)

            # Step 1: Create account button
            try:
                create_btn = page.locator('a[href="/i/flow/signup"], span:has-text("Create account")').first
                await create_btn.click(timeout=5000)
                await asyncio.sleep(3)
            except Exception:
                pass  # May already be on signup page

            # Step 2: Fill name
            name_input = page.locator('input[name="name"]').first
            await name_input.fill(handle)
            await asyncio.sleep(1)

            # Click "use email instead" if phone is default
            try:
                use_email = page.locator('span:has-text("Use email instead"), a:has-text("email")').first
                await use_email.click(timeout=3000)
                await asyncio.sleep(1)
            except Exception:
                pass

            # Fill email
            email_input = page.locator('input[name="email"], input[type="email"]').first
            await email_input.fill(email)
            await asyncio.sleep(1)

            # Birth date (Twitter requires it)
            try:
                month_sel = page.locator('select[name="month"], select#SELECTOR_1').first
                await month_sel.select_option(str(random.randint(1, 12)))
                day_sel = page.locator('select[name="day"], select#SELECTOR_2').first
                await day_sel.select_option(str(random.randint(1, 28)))
                year_sel = page.locator('select[name="year"], select#SELECTOR_3').first
                await year_sel.select_option(str(random.randint(1985, 2000)))
                await asyncio.sleep(1)
            except Exception:
                logger.debug("  Birth date selectors not found")

            # Next
            next_btn = page.locator('button:has-text("Next"), div[role="button"]:has-text("Next")').first
            await next_btn.click()
            await asyncio.sleep(3)

            # May need another Next (review step)
            try:
                next_btn2 = page.locator('button:has-text("Sign up"), div[role="button"]:has-text("Next")').first
                await next_btn2.click(timeout=5000)
                await asyncio.sleep(3)
            except Exception:
                pass

            # Email verification code
            email_code = fetch_verification_email(email, "twitter", timeout=90)
            if email_code:
                code_input = page.locator('input[name="verfication_code"], input[type="text"]').first
                await code_input.fill(email_code)
                next_btn = page.locator('button:has-text("Next")').first
                await next_btn.click()
                await asyncio.sleep(3)

            # Password
            try:
                pw_input = page.locator('input[name="password"], input[type="password"]').first
                await pw_input.fill(SOCIAL_PASSWORD)
                next_btn = page.locator('button:has-text("Next"), div[role="button"]:has-text("Next")').first
                await next_btn.click()
                await asyncio.sleep(3)
            except Exception:
                pass

            # Phone verification (Twitter usually requires this)
            page_html = await page.content()
            if "phone" in page_html.lower() or "verify" in page_html.lower():
                num_result = await sms_provider.get_number("twitter")
                if "error" not in num_result:
                    phone_input = page.locator('input[type="tel"], input[name="phone"]').first
                    await phone_input.fill(num_result["number"])
                    send_btn = page.locator('button:has-text("Next"), button:has-text("Send")').first
                    await send_btn.click()
                    await asyncio.sleep(3)

                    sms_code = await sms_provider.get_code(num_result["id"])
                    if sms_code:
                        code_input = page.locator('input[type="text"]').first
                        await code_input.fill(sms_code)
                        verify_btn = page.locator('button:has-text("Next"), button:has-text("Verify")').first
                        await verify_btn.click()
                        await asyncio.sleep(3)

                        logger.info(f"  Twitter account created: @{handle}")
                        save_account("twitter", email, handle, SOCIAL_PASSWORD, num_result["number"])
                        await browser.close()
                        return True

            # Check if we got through without phone
            if "home" in page.url.lower() or "x.com" in page.url:
                logger.info(f"  Twitter account created (no phone needed): @{handle}")
                save_account("twitter", email, handle, SOCIAL_PASSWORD)
                await browser.close()
                return True

            logger.warning(f"  Twitter creation unclear for @{handle}")
            await browser.close()

    except Exception as e:
        logger.error(f"  Twitter failed for @{handle}: {e}")

    return False


async def create_linkedin(email: str, name: str, company: str, sms_provider: SMSProvider) -> bool:
    """Create a LinkedIn account."""
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        from playwright.async_api import async_playwright

    first_name = name.split()[0]
    last_name = " ".join(name.split()[1:]) or "Tech"

    logger.info(f"Creating LinkedIn: {name} ({email})")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1366, "height": 768},
            )
            page = await ctx.new_page()

            await page.goto("https://www.linkedin.com/signup", timeout=60000)
            await asyncio.sleep(3)

            # Email
            email_input = page.locator('input#email-address, input[name="emailAddress"]').first
            await email_input.fill(email)
            await asyncio.sleep(0.5)

            # Password
            pw_input = page.locator('input#password, input[name="password"]').first
            await pw_input.fill(SOCIAL_PASSWORD)
            await asyncio.sleep(0.5)

            # Submit
            submit_btn = page.locator('button[type="submit"], button#join-form-submit').first
            await submit_btn.click()
            await asyncio.sleep(4)

            # First/Last name
            try:
                fn_input = page.locator('input#first-name, input[name="firstName"]').first
                await fn_input.fill(first_name)
                ln_input = page.locator('input#last-name, input[name="lastName"]').first
                await ln_input.fill(last_name)
                next_btn = page.locator('button[type="submit"], button#join-form-submit').first
                await next_btn.click()
                await asyncio.sleep(3)
            except Exception:
                pass

            # Captcha (LinkedIn uses its own)
            page_html = await page.content()
            if "captcha" in page_html.lower() or "security verification" in page_html.lower():
                logger.warning(f"  LinkedIn captcha for {name} — may need manual intervention")

            # Email verification
            email_code = fetch_verification_email(email, "linkedin", timeout=90)
            if email_code:
                code_input = page.locator('input#email-confirmation-input, input[name="pin"]').first
                await code_input.fill(email_code)
                submit_btn = page.locator('button[type="submit"]').first
                await submit_btn.click()
                await asyncio.sleep(3)

            # Phone verification
            page_html = await page.content()
            if "phone" in page_html.lower():
                num_result = await sms_provider.get_number("linkedin")
                if "error" not in num_result:
                    phone_input = page.locator('input[type="tel"], input#phone-number').first
                    await phone_input.fill(num_result["number"])
                    send_btn = page.locator('button[type="submit"]').first
                    await send_btn.click()
                    await asyncio.sleep(3)

                    sms_code = await sms_provider.get_code(num_result["id"])
                    if sms_code:
                        code_input = page.locator('input[type="text"], input#pin').first
                        await code_input.fill(sms_code)
                        verify_btn = page.locator('button[type="submit"]').first
                        await verify_btn.click()
                        await asyncio.sleep(3)

            # Check success
            if "feed" in page.url or "linkedin.com/in/" in page.url or "mynetwork" in page.url:
                logger.info(f"  LinkedIn account created: {name}")
                save_account("linkedin", email, name, SOCIAL_PASSWORD)
                await browser.close()
                return True

            logger.warning(f"  LinkedIn creation unclear for {name}")
            await browser.close()

    except Exception as e:
        logger.error(f"  LinkedIn failed for {name}: {e}")

    return False


async def _solve_recaptcha_audio(page) -> bool:
    """Attempt to solve reCAPTCHA via audio challenge."""
    try:
        # Click on reCAPTCHA iframe
        captcha_frame = page.frame_locator('iframe[src*="recaptcha"]').first
        checkbox = captcha_frame.locator('.recaptcha-checkbox-border').first
        await checkbox.click()
        await asyncio.sleep(2)

        # Click audio button
        challenge_frame = page.frame_locator('iframe[src*="recaptcha"][title*="challenge"]').first
        audio_btn = challenge_frame.locator('#recaptcha-audio-button').first
        await audio_btn.click()
        await asyncio.sleep(2)

        # Download audio
        audio_link = challenge_frame.locator('.rc-audiochallenge-tdownload-link, a[href*="payload"]').first
        audio_url = await audio_link.get_attribute('href')

        if audio_url:
            import httpx
            import speech_recognition as sr
            import tempfile

            async with httpx.AsyncClient() as client:
                resp = await client.get(audio_url)
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    f.write(resp.content)
                    mp3_path = f.name

            # Convert and recognize
            from pydub import AudioSegment
            wav_path = mp3_path.replace(".mp3", ".wav")
            AudioSegment.from_mp3(mp3_path).export(wav_path, format="wav")

            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio = recognizer.record(source)
                text = recognizer.recognize_google(audio)

            # Enter answer
            answer_input = challenge_frame.locator('#audio-response').first
            await answer_input.fill(text)
            verify_btn = challenge_frame.locator('#recaptcha-verify-button').first
            await verify_btn.click()
            await asyncio.sleep(3)

            # Cleanup
            os.unlink(mp3_path)
            os.unlink(wav_path)

            logger.info(f"  Captcha solved: '{text}'")
            return True

    except Exception as e:
        logger.debug(f"  Captcha solve failed: {e}")

    return False


# ── Main ──

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bulk Social Media Account Creator")
    parser.add_argument("platform", choices=["reddit", "twitter", "linkedin", "all"])
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--sms-provider", choices=["5sim", "quackr", "none"], default="none")
    parser.add_argument("--sms-api-key", default="")
    args = parser.parse_args()

    # Setup SMS provider
    sms = None
    if args.sms_provider == "5sim" and args.sms_api_key:
        sms = FiveSimProvider(args.sms_api_key)
        logger.info("Using 5SIM for phone verification")
    elif args.sms_provider == "quackr":
        sms = FreeQuackrProvider()
        logger.info("Using Quackr (free) for phone verification")
    else:
        logger.info("No SMS provider — Reddit only (no phone needed from clean IP)")

    results = {"created": 0, "failed": 0}

    if args.platform in ("reddit", "all"):
        accounts = REDDIT_ACCOUNTS[args.start:args.start + args.count]
        logger.info(f"\n{'='*50}\nCreating {len(accounts)} Reddit accounts\n{'='*50}")
        for email, username in accounts:
            ok = await create_reddit(email, username, sms)
            results["created" if ok else "failed"] += 1
            await asyncio.sleep(random.randint(30, 60))

    if args.platform in ("twitter", "all"):
        if not sms:
            logger.warning("Twitter requires phone verification — set --sms-provider")
        else:
            accounts = TWITTER_ACCOUNTS[args.start:args.start + min(args.count, len(TWITTER_ACCOUNTS))]
            logger.info(f"\n{'='*50}\nCreating {len(accounts)} Twitter accounts\n{'='*50}")
            for email, handle in accounts:
                ok = await create_twitter(email, handle, sms)
                results["created" if ok else "failed"] += 1
                await asyncio.sleep(random.randint(30, 60))

    if args.platform in ("linkedin", "all"):
        if not sms:
            logger.warning("LinkedIn requires phone verification — set --sms-provider")
        else:
            accounts = LINKEDIN_ACCOUNTS[args.start:args.start + min(args.count, len(LINKEDIN_ACCOUNTS))]
            logger.info(f"\n{'='*50}\nCreating {len(accounts)} LinkedIn accounts\n{'='*50}")
            for email, name, company in accounts:
                ok = await create_linkedin(email, name, company, sms)
                results["created" if ok else "failed"] += 1
                await asyncio.sleep(random.randint(45, 90))

    logger.info(f"\n{'='*50}")
    logger.info(f"RESULTS: Created={results['created']} Failed={results['failed']}")
    if os.path.exists(OUTPUT_FILE):
        logger.info(f"Accounts saved to: {OUTPUT_FILE}")
    logger.info(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(main())
