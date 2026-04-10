#!/usr/bin/env python3
"""Create domains and email accounts in Stalwart via REST API.

Requires port-forward: kubectl port-forward -n stalwart pod/stalwart-0 18080:8080

Usage: python3 scripts/setup_stalwart_api.py
"""

import json
import os
import sys
import urllib.request
import urllib.error
import base64

STALWART_URL = "http://localhost:18080"
ADMIN_USER = "admin"
ADMIN_PASS = "9TYNmAqI6WEwjpg6xPuCCFXgKv2qov2U7GadOe0ta1A="
DOMAINS_FILE = os.path.join(os.path.dirname(__file__), "domains.txt")
DEFAULT_PASSWORD = "Nubo@2026!Secure"
ACCOUNTS = ["sales", "info", "hello", "team", "support"]
QUOTA = 1073741824  # 1GB

auth_header = "Basic " + base64.b64encode(f"{ADMIN_USER}:{ADMIN_PASS}".encode()).decode()


def api_request(method, path, data=None):
    url = f"{STALWART_URL}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, json.loads(resp.read().decode()) if resp.read else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return e.code, body
    except Exception as e:
        return 0, str(e)


def create_domain(domain):
    """Create a domain in Stalwart."""
    data = {
        "type": "domain",
        "name": domain,
    }
    code, resp = api_request("POST", "/api/principal", data)
    if code in (200, 201):
        return True, "created"
    elif code == 409 or "already exists" in str(resp):
        return True, "exists"
    else:
        return False, f"error {code}: {resp}"


def create_account(email, display_name, password, domain):
    """Create an email account in Stalwart."""
    data = {
        "type": "individual",
        "name": email,
        "description": display_name,
        "secrets": [password],
        "emails": [email],
        "quota": QUOTA,
        "roles": ["user"],
        "memberOf": [f"domain:{domain}"] if False else [],  # Stalwart auto-associates
    }
    code, resp = api_request("POST", "/api/principal", data)
    if code in (200, 201):
        return True, "created"
    elif code == 409 or "already exists" in str(resp):
        return True, "exists"
    else:
        return False, f"error {code}: {resp}"


# Brand name mapping
BRANDS = {
    "hostingduty": "HostingDuty", "emailsify": "Emailsify", "postly": "Postly",
    "netemailsify": "NetEmailsify", "netpostio": "NetPostio", "buttonbada": "ButtonBada",
    "digipins": "DigiPins", "kaizeninfosys": "Kaizen Infosys", "onewarehouse": "OneWarehouse",
    "0xlabs": "0xLabs", "puneix": "Puneix", "marketx": "MarketX", "mktx": "MKTX",
    "tezcms": "TezCMS", "digitalgappa": "DigitalGappa",
    "chandorkartechnologies": "Chandorkar Technologies", "chandorkarlabs": "Chandorkar Labs",
    "streesakhi": "StreeSakhi", "nebulaproject": "Nebula Project", "logiclane": "LogicLane",
    "nubopay": "NuboPay", "uid": "UID", "nubo": "Nubo", "cybercartel": "CyberCartel",
    "tez": "Tez", "rotarycms": "RotaryCMS", "cli": "CLI.coffee",
}

DISPLAY_NAMES = {
    "sales": "Sales Team", "info": "Info", "hello": "Hello",
    "team": "Team", "support": "Support",
}


def main():
    with open(DOMAINS_FILE) as f:
        domains = [line.strip() for line in f if line.strip()]

    total_domains = 0
    total_accounts = 0
    created_domains = 0
    created_accounts = 0

    print(f"=== Stalwart Setup: {len(domains)} domains, {len(domains) * len(ACCOUNTS)} accounts ===\n")

    for domain in domains:
        print(f"--- {domain} ---")

        # Create domain
        ok, msg = create_domain(domain)
        status_icon = "+" if msg == "created" else "=" if msg == "exists" else "X"
        print(f"  [{status_icon}] Domain: {domain} ({msg})")
        total_domains += 1
        if msg == "created":
            created_domains += 1

        # Create accounts
        brand = BRANDS.get(domain.split(".")[0], domain.split(".")[0].title())
        for prefix in ACCOUNTS:
            email = f"{prefix}@{domain}"
            display_name = f"{DISPLAY_NAMES[prefix]} - {brand}"

            ok, msg = create_account(email, display_name, DEFAULT_PASSWORD, domain)
            status_icon = "+" if msg == "created" else "=" if msg == "exists" else "X"
            print(f"  [{status_icon}] {email} ({msg})")
            total_accounts += 1
            if msg == "created":
                created_accounts += 1

    print(f"\n=== Summary ===")
    print(f"Domains: {created_domains} created / {total_domains} total")
    print(f"Accounts: {created_accounts} created / {total_accounts} total")
    print(f"Password: {DEFAULT_PASSWORD}")


if __name__ == "__main__":
    main()
