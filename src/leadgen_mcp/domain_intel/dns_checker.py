"""DNS health checker — analyze MX, SPF, DMARC, DKIM, A/AAAA, and NS records."""

import dns.resolver
import dns.exception


# Common DKIM selectors used by popular providers
COMMON_DKIM_SELECTORS = [
    "default", "google", "selector1", "selector2",  # Microsoft 365
    "k1", "k2",  # Mailchimp
    "s1", "s2",  # Generic
    "dkim", "mail", "smtp",
    "mandrill", "everlytickey1", "cm",  # ESPs
]

# Timeout for each DNS query
DNS_TIMEOUT = 8.0


def check_dns(domain: str) -> dict:
    """Run a full DNS health check on a domain and return findings with severity ratings.

    Checks: A, AAAA, MX, SPF (TXT), DMARC (_dmarc), DKIM (common selectors), NS.
    """
    findings: dict = {
        "domain": domain,
        "records": {},
        "issues": [],
        "summary": {},
    }

    resolver = dns.resolver.Resolver()
    resolver.timeout = DNS_TIMEOUT
    resolver.lifetime = DNS_TIMEOUT

    # --- A Records ---
    a_records = _query(resolver, domain, "A")
    findings["records"]["A"] = a_records
    if not a_records:
        findings["issues"].append({
            "check": "A_RECORD",
            "issue": "No A record found",
            "detail": f"{domain} does not resolve to an IPv4 address",
            "severity": "critical",
        })
        findings["summary"]["resolves"] = False
    else:
        findings["summary"]["resolves"] = True

    # --- AAAA Records ---
    aaaa_records = _query(resolver, domain, "AAAA")
    findings["records"]["AAAA"] = aaaa_records
    findings["summary"]["ipv6"] = bool(aaaa_records)

    # --- NS Records ---
    ns_records = _query(resolver, domain, "NS")
    findings["records"]["NS"] = ns_records
    if ns_records:
        findings["summary"]["dns_provider"] = _identify_dns_provider(ns_records)
    else:
        findings["summary"]["dns_provider"] = "unknown"

    # --- MX Records ---
    mx_records = _query(resolver, domain, "MX")
    findings["records"]["MX"] = mx_records
    if not mx_records:
        findings["issues"].append({
            "check": "MX_RECORD",
            "issue": "No MX records — no email infrastructure",
            "detail": (
                f"{domain} has no mail exchange records. "
                "They cannot receive email and likely have no business email set up."
            ),
            "severity": "warning",
        })
        findings["summary"]["has_email"] = False
    else:
        findings["summary"]["has_email"] = True
        findings["summary"]["mail_provider"] = _identify_mail_provider(mx_records)

    # --- SPF Record (TXT) ---
    spf_record = _find_spf(resolver, domain)
    findings["records"]["SPF"] = spf_record
    if not spf_record:
        findings["issues"].append({
            "check": "SPF",
            "issue": "No SPF record — email deliverability risk",
            "detail": (
                f"{domain} has no SPF (Sender Policy Framework) TXT record. "
                "Emails from this domain are more likely to land in spam."
            ),
            "severity": "warning",
        })
        findings["summary"]["has_spf"] = False
    else:
        findings["summary"]["has_spf"] = True
        # Check for overly permissive SPF
        if "+all" in spf_record:
            findings["issues"].append({
                "check": "SPF_PERMISSIVE",
                "issue": "SPF record is dangerously permissive (+all)",
                "detail": "SPF allows any server to send email on behalf of this domain",
                "severity": "critical",
            })

    # --- DMARC Record ---
    dmarc_record = _find_dmarc(resolver, domain)
    findings["records"]["DMARC"] = dmarc_record
    if not dmarc_record:
        findings["issues"].append({
            "check": "DMARC",
            "issue": "No DMARC record — email security gap",
            "detail": (
                f"{domain} has no DMARC policy. This domain is vulnerable to "
                "email spoofing and phishing impersonation."
            ),
            "severity": "warning",
        })
        findings["summary"]["has_dmarc"] = False
    else:
        findings["summary"]["has_dmarc"] = True
        # Check DMARC policy strength
        if "p=none" in dmarc_record:
            findings["issues"].append({
                "check": "DMARC_WEAK",
                "issue": "DMARC policy set to 'none' — monitoring only, not enforcing",
                "detail": "DMARC is configured but does not reject or quarantine spoofed emails",
                "severity": "info",
            })

    # --- DKIM (common selectors) ---
    dkim_found = _find_dkim(resolver, domain)
    findings["records"]["DKIM"] = dkim_found
    if not dkim_found:
        findings["issues"].append({
            "check": "DKIM",
            "issue": "No DKIM records found for common selectors",
            "detail": (
                f"No DKIM signing detected for {domain} using common selectors. "
                "Email authentication may be incomplete."
            ),
            "severity": "info",
        })
        findings["summary"]["has_dkim"] = False
    else:
        findings["summary"]["has_dkim"] = True

    # --- Overall severity ---
    severities = [i["severity"] for i in findings["issues"]]
    if "critical" in severities:
        findings["severity"] = "critical"
    elif "warning" in severities:
        findings["severity"] = "warning"
    elif "info" in severities:
        findings["severity"] = "info"
    else:
        findings["severity"] = "good"

    findings["issue_count"] = len(findings["issues"])

    return findings


def _query(resolver: dns.resolver.Resolver, domain: str, rdtype: str) -> list[str]:
    """Query DNS and return list of record strings, or empty list on failure."""
    try:
        answers = resolver.resolve(domain, rdtype)
        return [str(rdata) for rdata in answers]
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN,
            dns.resolver.NoNameservers, dns.exception.Timeout,
            dns.resolver.LifetimeTimeout, Exception):
        return []


def _find_spf(resolver: dns.resolver.Resolver, domain: str) -> str | None:
    """Look for an SPF record in the domain's TXT records."""
    txt_records = _query(resolver, domain, "TXT")
    for record in txt_records:
        clean = record.strip('"')
        if clean.startswith("v=spf1"):
            return clean
    return None


def _find_dmarc(resolver: dns.resolver.Resolver, domain: str) -> str | None:
    """Look for a DMARC record at _dmarc.<domain>."""
    txt_records = _query(resolver, f"_dmarc.{domain}", "TXT")
    for record in txt_records:
        clean = record.strip('"')
        if clean.startswith("v=DMARC1"):
            return clean
    return None


def _find_dkim(resolver: dns.resolver.Resolver, domain: str) -> list[dict]:
    """Check common DKIM selectors for the domain."""
    found = []
    for selector in COMMON_DKIM_SELECTORS:
        dkim_domain = f"{selector}._domainkey.{domain}"
        records = _query(resolver, dkim_domain, "TXT")
        if records:
            found.append({"selector": selector, "record": records[0][:120]})
        if len(found) >= 3:
            break  # Enough to confirm DKIM exists
    return found


def _identify_mail_provider(mx_records: list[str]) -> str:
    """Identify the email provider from MX records."""
    mx_lower = " ".join(mx_records).lower()
    providers = {
        "google.com": "Google Workspace",
        "googlemail.com": "Google Workspace",
        "outlook.com": "Microsoft 365",
        "protection.outlook.com": "Microsoft 365",
        "pphosted.com": "Proofpoint",
        "mimecast.com": "Mimecast",
        "zoho.com": "Zoho Mail",
        "yahoodns.net": "Yahoo Mail",
        "mailgun.org": "Mailgun",
        "sendgrid.net": "SendGrid",
        "secureserver.net": "GoDaddy",
        "registrar-servers.com": "Namecheap",
    }
    for pattern, provider in providers.items():
        if pattern in mx_lower:
            return provider
    return "other"


def _identify_dns_provider(ns_records: list[str]) -> str:
    """Identify the DNS provider from NS records."""
    ns_lower = " ".join(ns_records).lower()
    providers = {
        "cloudflare.com": "Cloudflare",
        "awsdns": "AWS Route 53",
        "googledomains.com": "Google Domains",
        "domaincontrol.com": "GoDaddy",
        "registrar-servers.com": "Namecheap",
        "digitalocean.com": "DigitalOcean",
        "linode.com": "Linode",
        "hetzner.com": "Hetzner",
        "azure-dns.com": "Azure DNS",
        "nsone.net": "NS1",
        "dynect.net": "Oracle Dyn",
    }
    for pattern, provider in providers.items():
        if pattern in ns_lower:
            return provider
    return "other"
