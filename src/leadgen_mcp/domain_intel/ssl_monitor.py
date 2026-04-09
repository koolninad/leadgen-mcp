"""SSL certificate monitor — check expiry, issuer, chain validity, and cipher strength."""

import ssl
import socket
from datetime import datetime, timezone


# Weak ciphers that indicate poor security configuration
WEAK_CIPHERS = {
    "RC4", "DES", "3DES", "MD5", "NULL", "EXPORT", "anon",
}


def check_ssl(domain: str, port: int = 443) -> dict:
    """Analyze the SSL/TLS certificate for a domain.

    Returns certificate details, expiry analysis, issuer info,
    chain validity, and cipher strength assessment.
    """
    hostname = domain.split(":")[0].strip()
    result: dict = {
        "domain": hostname,
        "port": port,
        "issues": [],
    }

    # --- Certificate fetch ---
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                cipher_info = ssock.cipher()
                protocol = ssock.version()

                if not cert:
                    result["error"] = "No certificate returned by server"
                    result["severity"] = "critical"
                    return result

                result.update(_parse_certificate(cert))
                result["protocol"] = protocol
                result["cipher"] = {
                    "name": cipher_info[0] if cipher_info else None,
                    "protocol": cipher_info[1] if cipher_info else None,
                    "bits": cipher_info[2] if cipher_info else None,
                }

    except ssl.SSLCertVerificationError as e:
        result["valid"] = False
        result["error"] = f"Certificate verification failed: {e}"
        result["issues"].append({
            "issue": "Invalid SSL certificate",
            "detail": str(e),
            "severity": "critical",
        })
        result["severity"] = "critical"
        return result
    except socket.timeout:
        result["error"] = f"Connection to {hostname}:{port} timed out"
        result["severity"] = "critical"
        return result
    except ConnectionRefusedError:
        result["error"] = f"Connection refused on {hostname}:{port} — SSL not configured"
        result["severity"] = "critical"
        return result
    except OSError as e:
        result["error"] = f"SSL check failed: {e}"
        result["severity"] = "critical"
        return result

    # --- Expiry analysis ---
    if result.get("days_until_expiry") is not None:
        days_left = result["days_until_expiry"]
        if days_left < 0:
            result["issues"].append({
                "issue": "SSL certificate has EXPIRED",
                "detail": f"Certificate expired {abs(days_left)} days ago — site is insecure",
                "severity": "critical",
            })
        elif days_left <= 7:
            result["issues"].append({
                "issue": "SSL certificate expires within 7 days",
                "detail": f"Certificate expires in {days_left} days — URGENT renewal needed",
                "severity": "critical",
            })
        elif days_left <= 30:
            result["issues"].append({
                "issue": "SSL certificate expiring soon",
                "detail": f"Certificate expires in {days_left} days — renewal recommended",
                "severity": "warning",
            })

    # --- Issuer analysis ---
    issuer_org = result.get("issuer", {}).get("organizationName", "")
    issuer_cn = result.get("issuer", {}).get("commonName", "")
    if "let's encrypt" in issuer_org.lower() or "let's encrypt" in issuer_cn.lower():
        result["issuer_type"] = "free"
        result["issuer_name"] = "Let's Encrypt"
    elif "self-signed" in str(result.get("error", "")).lower():
        result["issuer_type"] = "self_signed"
        result["issues"].append({
            "issue": "Self-signed certificate",
            "detail": "Browsers will show security warnings to visitors",
            "severity": "critical",
        })
    else:
        result["issuer_type"] = "commercial"
        result["issuer_name"] = issuer_org or issuer_cn or "unknown"

    # --- Protocol check ---
    if protocol and protocol in ("TLSv1", "TLSv1.1", "SSLv3", "SSLv2"):
        result["issues"].append({
            "issue": f"Outdated TLS protocol: {protocol}",
            "detail": f"Using deprecated {protocol} — should upgrade to TLS 1.2 or 1.3",
            "severity": "warning",
        })

    # --- Cipher strength ---
    cipher_name = result.get("cipher", {}).get("name", "")
    cipher_bits = result.get("cipher", {}).get("bits", 256)
    if cipher_name:
        for weak in WEAK_CIPHERS:
            if weak.lower() in cipher_name.lower():
                result["issues"].append({
                    "issue": f"Weak cipher detected: {cipher_name}",
                    "detail": "This cipher is considered insecure and should be disabled",
                    "severity": "warning",
                })
                break
        if cipher_bits and cipher_bits < 128:
            result["issues"].append({
                "issue": f"Low cipher strength: {cipher_bits} bits",
                "detail": "Cipher key length below 128 bits is considered weak",
                "severity": "warning",
            })

    # --- Overall severity ---
    severities = [i["severity"] for i in result["issues"]]
    if "critical" in severities:
        result["severity"] = "critical"
    elif "warning" in severities:
        result["severity"] = "warning"
    else:
        result["severity"] = "good"

    result["issue_count"] = len(result["issues"])
    result["is_urgent_lead"] = result.get("days_until_expiry", 999) < 30

    return result


def _parse_certificate(cert: dict) -> dict:
    """Parse a Python ssl certificate dict into clean fields."""
    now = datetime.now(timezone.utc)

    # Expiry
    not_after_str = cert.get("notAfter", "")
    not_before_str = cert.get("notBefore", "")

    not_after = _parse_cert_date(not_after_str)
    not_before = _parse_cert_date(not_before_str)

    days_until_expiry = (not_after - now).days if not_after else None

    # Subject and issuer
    subject = {}
    for rdn in cert.get("subject", ()):
        for key, value in rdn:
            subject[key] = value

    issuer = {}
    for rdn in cert.get("issuer", ()):
        for key, value in rdn:
            issuer[key] = value

    # SANs
    san_list = []
    for san_type, san_value in cert.get("subjectAltName", ()):
        san_list.append(san_value)

    return {
        "valid": True,
        "subject": subject,
        "issuer": issuer,
        "not_before": not_before.isoformat() if not_before else None,
        "not_after": not_after.isoformat() if not_after else None,
        "days_until_expiry": days_until_expiry,
        "subject_alt_names": san_list[:20],
        "serial_number": cert.get("serialNumber"),
    }


def _parse_cert_date(date_str: str) -> datetime | None:
    """Parse SSL certificate date string (e.g., 'Jan  5 00:00:00 2025 GMT')."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
