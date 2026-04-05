"""Domain lookup via python-whois, DNS records, and HTTP headers."""

import json
import socket
import urllib.request
import urllib.error

from tools import register


@register("domain_lookup")
def lookup(domain: str) -> dict:
    """Get WHOIS, DNS, and HTTP header info for a domain."""
    results = {}
    errors = []

    # WHOIS
    whois_data = _whois_lookup(domain)
    if isinstance(whois_data, str):
        errors.append(whois_data)
    else:
        results["whois"] = whois_data

    # DNS resolution
    dns_data = _dns_lookup(domain)
    if isinstance(dns_data, str):
        errors.append(dns_data)
    else:
        results["dns"] = dns_data

    # HTTP headers / tech detection
    http_data = _http_probe(domain)
    if isinstance(http_data, str):
        errors.append(http_data)
    else:
        results["http"] = http_data

    output = {
        "tool": "domain",
        "query": domain,
        "results": results,
        "has_data": bool(results),
    }
    if errors:
        output["warnings"] = errors
    return output


def _whois_lookup(domain: str) -> dict | str:
    """Run python-whois on a domain."""
    try:
        import whois
    except ImportError:
        return "python-whois not installed. Run: pip install python-whois"

    try:
        w = whois.whois(domain)

        data = {}
        for key in ["domain_name", "registrar", "creation_date", "expiration_date",
                     "name_servers", "org", "country", "state", "city", "emails"]:
            val = getattr(w, key, None)
            if val is None:
                continue
            if isinstance(val, list):
                val = [str(v) for v in val]
            else:
                val = str(val)
            data[key] = val

        return data if data else "No WHOIS data found"

    except Exception as e:
        return f"WHOIS lookup failed: {e}"


def _dns_lookup(domain: str) -> dict | str:
    """Resolve DNS records for a domain."""
    results = {}

    # A records (IPv4)
    try:
        addrs = socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)
        ips = list({addr[4][0] for addr in addrs})
        if ips:
            results["a_records"] = ips
    except socket.gaierror:
        pass

    # AAAA records (IPv6)
    try:
        addrs = socket.getaddrinfo(domain, None, socket.AF_INET6, socket.SOCK_STREAM)
        ips = list({addr[4][0] for addr in addrs})
        if ips:
            results["aaaa_records"] = ips
    except socket.gaierror:
        pass

    # Reverse DNS on first IP
    if results.get("a_records"):
        try:
            hostname = socket.gethostbyaddr(results["a_records"][0])
            results["reverse_dns"] = hostname[0]
        except (socket.herror, socket.gaierror):
            pass

    if not results:
        return "DNS resolution failed"

    return results


def _http_probe(domain: str) -> dict | str:
    """Probe HTTP headers to detect server tech."""
    for scheme in ("https", "http"):
        try:
            req = urllib.request.Request(
                f"{scheme}://{domain}",
                method="HEAD",
                headers={"user-agent": "traceback-osint"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                headers = dict(resp.headers)

                data = {
                    "url": resp.url,
                    "status": resp.status,
                }

                # Extract useful headers
                interesting = {
                    "server": "server",
                    "x-powered-by": "powered_by",
                    "content-type": "content_type",
                    "x-frame-options": "x_frame_options",
                    "strict-transport-security": "hsts",
                    "content-security-policy": "csp",
                    "x-content-type-options": "x_content_type_options",
                }

                tech = {}
                for header, label in interesting.items():
                    val = headers.get(header) or headers.get(header.title())
                    if val:
                        tech[label] = val

                if tech:
                    data["tech"] = tech

                # Security header check
                security_headers = ["strict-transport-security", "content-security-policy",
                                    "x-frame-options", "x-content-type-options"]
                present = sum(1 for h in security_headers if h in (k.lower() for k in headers))
                data["security_score"] = f"{present}/{len(security_headers)} security headers present"

                return data

        except (urllib.error.URLError, OSError):
            continue

    return "HTTP probe failed — site may be down or blocking requests"
