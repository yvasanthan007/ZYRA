"""
backend/url_analyzer/ssl_analyzer.py — SSL/TLS certificate analysis

Inspects the HTTPS endpoint of the target using only the Python standard
library (ssl + socket):

    - Certificate validity (chain verification via the system trust store)
    - Expiration date + remaining validity days
    - Issuer / subject common names
    - Hostname mismatch detection
    - Negotiated TLS version and cipher

When certificate verification fails, a second unverified handshake is used
to still retrieve certificate metadata so the report can explain WHY the
certificate failed. SSRF guards are re-checked before every connection.
"""

import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

from backend.url_analyzer.validator import (
    TLS_TIMEOUT,
    is_blocked_ip,
    resolve_host_ips,
)


def _cert_datetime(value: str):
    """Parse an ASN.1/SSL notBefore/notAfter string into a datetime (UTC)."""
    try:
        return datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _safe_connect(hostname: str, port: int, context: ssl.SSLContext, timeout: float):
    """Open a TLS connection, returning (sock, error)."""
    try:
        raw = socket.create_connection((hostname, port), timeout=timeout)
        sock = context.wrap_socket(raw, server_hostname=hostname)
        return sock, None
    except Exception as e:
        return None, e


def _decode_der(der: bytes):
    """Decode DER certificate bytes via a temp file (stdlib-only decode)."""
    import os
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix=".der", delete=False) as tf:
            tf.write(der)
            tmp_path = tf.name
        try:
            return ssl._ssl._test_decode_cert(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception:
        return None


def analyze_ssl(url: str, parts: dict) -> dict:
    """
    Analyze the SSL/TLS configuration of the target.

    Args:
        url    — normalized URL string
        parts  — dict from validator.validate_url()
    Returns a structured dict for the result payload.
    """
    scheme = (parts.get("scheme") or "").lower()
    hostname = parts.get("hostname") or ""
    port = parts.get("port") or 443

    info = {
        "checked": False,
        "status": "unknown",       # valid | invalid | not_https | unreachable
        "https_enabled": scheme == "https",
        "valid": False,
        "issuer": None,
        "subject": None,
        "expires": None,
        "expires_in_days": None,
        "not_before": None,
        "self_signed": False,
        "hostname_mismatch": False,
        "tls_version": None,
        "cipher": None,
        "san": [],
        "error": None,
    }

    if scheme != "https":
        info["status"] = "not_https"
        info["error"] = "Target does not use HTTPS — SSL/TLS analysis skipped."
        return info

    # SSRF guard: re-resolve and block private targets before connecting.
    ok, ips_or_err = resolve_host_ips(hostname)
    if ok:
        for ip in ips_or_err:
            if is_blocked_ip(ip):
                info["status"] = "unreachable"
                info["error"] = "Target resolves to a blocked (private/internal) address."
                return info

    # 1) Strict, verifying handshake
    strict_ctx = ssl.create_default_context()
    sock, err = _safe_connect(hostname, port, strict_ctx, TLS_TIMEOUT)
    if sock is not None:
        try:
            cert = sock.getpeercert() or {}
            info.update(_cert_fields(cert))
            info["checked"] = True
            info["valid"] = True
            info["status"] = "valid"
            info["tls_version"] = sock.version()
            cipher = sock.cipher()
            info["cipher"] = cipher[0] if cipher else None
        finally:
            try:
                sock.close()
            except OSError:
                pass
        return info

    # 2) Verification failed — retry unverified to fetch certificate metadata
    loose_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    loose_ctx.check_hostname = False
    loose_ctx.verify_mode = ssl.CERT_NONE
    sock2, err2 = _safe_connect(hostname, port, loose_ctx, TLS_TIMEOUT)
    if sock2 is not None:
        try:
            der = sock2.getpeercert(True)
            decoded = _decode_der(der) if der else None
            if decoded:
                info.update(_cert_fields(decoded))
            info["checked"] = True
            info["valid"] = False
            info["status"] = "invalid"
            info["tls_version"] = sock2.version()
            err_text = str(err) if err is not None else "certificate verification failed"
            if "hostname mismatch" in err_text.lower():
                info["hostname_mismatch"] = True
            if "self signed" in err_text.lower() or "self-signed" in err_text.lower():
                info["self_signed"] = True
            info["error"] = f"SSL/TLS certificate validation failed. ({err_text})"
        finally:
            try:
                sock2.close()
            except OSError:
                pass
        return info

    # 3) Connection itself failed
    info["checked"] = False
    info["status"] = "unreachable"
    info["error"] = _humanize_tls_error(err if err is not None else err2)
    return info


def _cert_fields(cert: dict) -> dict:
    """Extract report fields from a decoded peer-certificate dict."""
    issuer = cert.get("issuer") or []
    subject = cert.get("subject") or []

    def _cn(names):
        for rdn in names or []:
            for key, value in rdn:
                if key == "commonName":
                    return value
        return None

    days_left = None
    not_after_dt = _cert_datetime(cert.get("notAfter"))
    if not_after_dt is not None:
        days_left = int((not_after_dt - datetime.now(timezone.utc)).total_seconds() // 86400)

    issuer_cn = _cn(issuer)
    issuer_org = None
    for rdn in issuer:
        for key, value in rdn:
            if key == "organizationName":
                issuer_org = value
                break

    san = [value for kind, value in (cert.get("subjectAltName") or []) if kind == "DNS"]

    return {
        "issuer": issuer_cn or issuer_org,
        "subject": _cn(subject),
        "expires": cert.get("notAfter"),
        "expires_in_days": days_left,
        "not_before": cert.get("notBefore"),
        "san": san[:10],
    }


def _humanize_tls_error(err: Exception) -> str:
    """Convert a TLS/socket exception into a user-friendly message."""
    text = str(err)
    lowered = text.lower()
    if "timed out" in lowered or isinstance(err, socket.timeout):
        return "Unable to reach the destination within the allowed time."
    if "refused" in lowered:
        return "Connection refused — no service is listening on the TLS port."
    if "getaddrinfo" in lowered or "name or service not known" in lowered:
        return "Domain could not be resolved."
    if "ssl" in lowered:
        return f"SSL/TLS handshake failed. ({type(err).__name__})"
    return f"Connection failed. ({type(err).__name__})"


_ = urlparse  # namespace stability

