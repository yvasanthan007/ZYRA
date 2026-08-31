"""
backend/dns_lookup/resolver.py — Real DNS record resolution via dnspython

Every query in this module is a genuine DNS query issued through the
dnspython library (never a shell command), with hard timeouts and full
error capture so a single failing record type can never abort a lookup.

Record types covered:
    A, AAAA, CNAME, MX, NS, TXT (+ SPF / DMARC derived), SOA,
    PTR (reverse DNS), DNSSEC (DNSKEY + DS + AD flag)

Per-type result shape:
    {
        "type": "A",
        "records": [{"value": "...", "ttl": 3600}, ...],
        "ttl": 3600,           # lowest TTL in the set
        "count": 1,
        "status": "OK" | "NOT_FOUND" | "ERROR",
        "error": None | "human readable reason",
    }
"""

import time
from typing import Dict, List, Optional

import dns.exception
import dns.flags
import dns.reversename
import dns.resolver

# Query budgets (seconds)
RESOLVE_TIMEOUT = 3.0      # per nameserver attempt
RESOLVE_LIFETIME = 8.0     # total budget per record-type query
DNSSEC_LIFETIME = 6.0      # total budget for DNSKEY / DS queries
MAX_PTR_PROBES = 3         # reverse-DNS probes for A-record IPs

_PRIMARY_TYPES = ("A", "AAAA")
_OTHER_TYPES = ("CNAME", "MX", "NS", "TXT", "SOA")

# Types whose value is a hostname — displayed without the trailing dot
_HOSTNAME_TYPES = {"CNAME", "MX", "NS", "SOA", "PTR"}


def _clean_value(rdtype: str, value: str) -> str:
    """Normalize a record's text form (strip trailing dot on hostnames)."""
    value = (value or "").strip()
    if rdtype in _HOSTNAME_TYPES and value.endswith("."):
        # RFC 7505 null MX ("0 .") — keep the dot, it is the actual target
        tail = value.rsplit(" ", 1)[-1]
        if len(tail) > 1:
            value = value[:-1]
    return value


def _make_resolver() -> dns.resolver.Resolver:
    """A configured resolver with strict timeouts (never hangs a request)."""
    resolver = dns.resolver.Resolver(configure=True)
    resolver.timeout = RESOLVE_TIMEOUT
    resolver.lifetime = RESOLVE_LIFETIME
    return resolver


def _query_type(resolver: dns.resolver.Resolver, qname: str,
                rdtype: str, lifetime: float = RESOLVE_LIFETIME) -> Dict:
    """
    Run one record-type query and shape the result.
    Never raises — all DNS failures become a structured status.
    """
    result = {
        "type": rdtype,
        "records": [],
        "ttl": None,
        "count": 0,
        "status": "ERROR",
        "error": None,
    }
    try:
        answer = resolver.resolve(qname, rdtype, lifetime=lifetime)
    except dns.resolver.NXDOMAIN:
        result.update(status="NOT_FOUND",
                      error="Domain does not exist (NXDOMAIN).")
        return result
    except dns.resolver.NoAnswer:
        result.update(status="NOT_FOUND",
                      error=f"No {rdtype} records exist for this name.")
        return result
    except dns.resolver.NoNameservers:
        result.update(status="ERROR",
                      error=f"Authoritative nameservers failed for {rdtype} (SERVFAIL).")
        return result
    except dns.exception.Timeout:
        result.update(status="ERROR", error=f"{rdtype} query timed out.")
        return result
    except Exception as e:  # noqa: BLE001 — any resolver failure is captured
        result.update(status="ERROR",
                      error=f"{rdtype} query failed: {type(e).__name__}")
        return result

    rrset = answer.rrset
    values: List[Dict] = []
    if rrset is not None:
        for rdata in rrset:
            values.append({
                "value": _clean_value(rdtype, rdata.to_text()),
                "ttl": int(rrset.ttl),
            })
    values.sort(key=lambda r: r["value"])
    ttls = [r["ttl"] for r in values if r["ttl"] is not None]
    result.update({
        "records": values,
        "ttl": min(ttls) if ttls else None,
        "count": len(values),
        "status": "OK" if values else "NOT_FOUND",
        "error": None if values else f"No {rdtype} records returned.",
    })
    return result

# ──────────────────────────────────────────────
# Reverse DNS (PTR)
# ──────────────────────────────────────────────

def _reverse_query(resolver: dns.resolver.Resolver, ip: str) -> Dict:
    """PTR lookup for one address literal."""
    ptr = {
        "type": "PTR",
        "records": [],
        "ttl": None,
        "count": 0,
        "status": "ERROR",
        "error": None,
    }
    try:
        rev = dns.reversename.from_address(ip)
        answer = resolver.resolve(rev, "PTR", lifetime=RESOLVE_LIFETIME)
        rrset = answer.rrset
        values = [{"value": _clean_value("PTR", r.to_text()), "ttl": int(rrset.ttl)}
                  for r in rrset] if rrset is not None else []
        ttls = [r["ttl"] for r in values]
        ptr.update({
            "records": values,
            "ttl": min(ttls) if ttls else None,
            "count": len(values),
            "status": "OK" if values else "NOT_FOUND",
            "error": None if values else "No PTR record.",
        })
    except dns.resolver.NXDOMAIN:
        ptr.update(status="NOT_FOUND", error="No reverse zone (NXDOMAIN).")
    except dns.resolver.NoAnswer:
        ptr.update(status="NOT_FOUND", error="No PTR record for this address.")
    except dns.exception.Timeout:
        ptr.update(status="ERROR", error="PTR query timed out.")
    except Exception as e:  # noqa: BLE001
        ptr.update(status="ERROR", error=f"PTR query failed: {type(e).__name__}")
    return ptr


# ──────────────────────────────────────────────
# DNSSEC status (real DNSKEY / DS / AD-flag data)
# ──────────────────────────────────────────────

def _dnssec_status(resolver: dns.resolver.Resolver, apex: str) -> Dict:
    """
    Determine the DNSSEC posture of the zone from real DNS data:
      - DNSKEY at the zone  → the zone is signed
      - DS at the same name → parent-side delegation signer record
      - AD flag on answers  → a validating resolver verified the data

    Some recursive resolvers (notably Windows DNS forwarders) strip DNSKEY /
    DS answers; when that happens the query is retried once against well
    known public resolvers so the reported status stays accurate.
    """
    info = {
        "status": "NOT_ENABLED",
        "dnskey": False,
        "ds": False,
        "ad_flag": False,
        "key_count": 0,
        "detail": "No DNSSEC records were found for this domain.",
    }

    answer, ds_answer = _dnskey_via_any_resolver(resolver, apex)

    if answer is not None and answer.rrset is not None:
        info["dnskey"] = True
        info["key_count"] = len(answer.rrset)
        if answer.response is not None:
            info["ad_flag"] = bool(answer.response.flags & dns.flags.AD)

    if ds_answer is not None and ds_answer.rrset is not None:
        info["ds"] = len(ds_answer.rrset) > 0

    if info["dnskey"] and info["ad_flag"]:
        info["status"] = "ENABLED_VALIDATED"
        info["detail"] = ("Zone is signed (DNSKEY present) and responses were "
                          "verified by a validating resolver (AD flag set).")
    elif info["dnskey"]:
        info["status"] = "ENABLED"
        detail = f"Zone is signed with {info['key_count']} DNSKEY record(s)."
        detail += (" A DS record is published at the parent zone." if info["ds"]
                   else " No DS record was returned by the resolver.")
        info["detail"] = detail
    elif info["ds"]:
        info["status"] = "PARTIAL"
        info["detail"] = ("A DS record exists at the parent zone but no DNSKEY "
                          "was returned — the zone may be mid-migration.")
    return info


# Public resolvers used only as a fallback when the system resolver
# refuses/strips DNSSEC record types. These are real DNS queries.
_FALLBACK_NAMESERVERS = ("8.8.8.8", "1.1.1.1", "9.9.9.9")


def _dnskey_via_any_resolver(resolver, apex: str):
    """
    Return (dnskey_answer, ds_answer); either may be None.
    Tries the system resolver first, then public resolvers.
    """
    def attempt(nameservers):
        r = resolver
        if nameservers:
            r = dns.resolver.Resolver(configure=False)
            r.nameservers = list(nameservers)
            r.timeout = RESOLVE_TIMEOUT
            r.lifetime = DNSSEC_LIFETIME
        key_ans = None
        ds_ans = None
        try:
            key_ans = r.resolve(apex, "DNSKEY", lifetime=DNSSEC_LIFETIME)
        except Exception:  # noqa: BLE001
            key_ans = None
        try:
            ds_ans = r.resolve(apex, "DS", lifetime=DNSSEC_LIFETIME)
        except Exception:  # noqa: BLE001
            ds_ans = None
        return key_ans, ds_ans

    key_ans, ds_ans = attempt(None)
    if key_ans is None:
        # Retry through public resolvers (system resolver may strip DNSSEC RR types)
        for ns in _FALLBACK_NAMESERVERS:
            key_ans2, ds_ans2 = attempt((ns,))
            if key_ans2 is not None or ds_ans2 is not None:
                return key_ans2, ds_ans2 if key_ans2 is None else (key_ans2, ds_ans2 or ds_ans)
    return key_ans, ds_ans

# ──────────────────────────────────────────────
# TXT / SPF / DMARC helpers
# ──────────────────────────────────────────────

def _extract_spf(txt_block, domain: str,
                 resolver: dns.resolver.Resolver) -> Dict:
    """Pull the SPF policy from the TXT answer; query DMARC separately."""
    spf = {"present": False, "record": None, "all_policy": None, "error": None}
    if txt_block and txt_block.get("status") == "OK":
        for rec in txt_block.get("records", []):
            val = (rec.get("value") or "")
            if val.lower().startswith("v=spf1"):
                spf["present"] = True
                spf["record"] = val
                lowered = val.lower()
                for mech in ("+all", "-all", "~all", "?all"):
                    if mech in lowered:
                        spf["all_policy"] = mech
                        break
                break
        if not spf["present"]:
            spf["error"] = "No v=spf1 record found in TXT answers."

    dmarc = {"present": False, "record": None, "policy": None, "error": None}
    try:
        answer = resolver.resolve(f"_dmarc.{domain}", "TXT",
                                  lifetime=RESOLVE_LIFETIME)
        if answer.rrset is not None:
            for rdata in answer.rrset:
                val = _clean_value("TXT", rdata.to_text())
                if val.lower().startswith("v=dmarc1"):
                    dmarc["present"] = True
                    dmarc["record"] = val
                    for tag in ("p=reject", "p=quarantine", "p=none"):
                        if tag in val.lower():
                            dmarc["policy"] = tag.split("=", 1)[1]
                            break
                    break
            if not dmarc["present"]:
                dmarc["error"] = "No v=dmarc1 record at _dmarc."
    except Exception:  # noqa: BLE001 — absence of DMARC is normal
        dmarc["error"] = "No DMARC record found."

    return {"spf": spf, "dmarc": dmarc}


def _wildcard_probe(resolver: dns.resolver.Resolver, domain: str) -> Optional[bool]:
    """
    True/False when determined; None when inconclusive.
    A random subdomain resolving means wildcard DNS is active.
    A definitive NXDOMAIN / NoAnswer proves NO wildcard → False.
    """
    import secrets
    probe = f"zyra-{secrets.token_hex(6)}.livecheck.{domain}"
    try:
        answer = resolver.resolve(probe, "A", lifetime=RESOLVE_LIFETIME)
        return bool(answer.rrset is not None and len(answer.rrset) > 0)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False  # definitive: no wildcard
    except Exception:  # noqa: BLE001 — timeouts etc. stay inconclusive
        return None


# ──────────────────────────────────────────────
# The full resolution pass
# ──────────────────────────────────────────────

def resolve_all(domain: str, is_ip: bool = False, apex: str = None) -> Dict:
    """
    Run every DNS query for the target and return the structured record set,
    response timings, DNSSEC posture and reverse-DNS information.

    `apex` is the registered domain (e.g. example.com for www.example.com);
    DNSSEC and wildcard checks are performed there.
    """
    started = time.perf_counter()
    resolver = _make_resolver()
    apex = (apex or domain).strip().lower() or domain

    out: Dict = {
        "records": {},
        "resolution": {"resolved": False, "ips": [], "error": None},
        "dnssec": {},
        "txt_policy": {},
        "reverse": {},
        "wildcard": None,
        "response_time_ms": None,
        "total_time_ms": None,
    }

    # ── Bare IP: skip forward lookups, go straight to reverse ──
    if is_ip:
        out["response_time_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        ptr = _reverse_query(resolver, domain)
        out["records"]["PTR"] = ptr
        out["reverse"] = {
            "queried_ips": [domain],
            "hostnames": [r["value"] for r in ptr.get("records", [])],
            "any_found": ptr.get("status") == "OK",
        }
        out["resolution"] = {"resolved": True, "ips": [domain], "error": None}
        out["total_time_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        return out

    # ── Primary address records (A / AAAA) ──
    primary = {}
    for rdtype in _PRIMARY_TYPES:
        primary[rdtype] = _query_type(resolver, domain, rdtype)
        out["records"][rdtype] = primary[rdtype]

    a_ok = primary["A"]["status"] == "OK"
    aaaa_ok = primary["AAAA"]["status"] == "OK"
    out["response_time_ms"] = round((time.perf_counter() - started) * 1000.0, 1)

    if a_ok or aaaa_ok:
        out["resolution"]["resolved"] = True
        out["resolution"]["ips"] = (
            ([r["value"] for r in primary["A"]["records"]] if a_ok else [])
            + ([r["value"] for r in primary["AAAA"]["records"]] if aaaa_ok else [])
        )
    else:
        err = primary["A"].get("error") or primary["AAAA"].get("error")
        out["resolution"]["error"] = err or "Domain could not be resolved."

    # ── CNAME / MX / NS / TXT / SOA ──
    for rdtype in _OTHER_TYPES:
        out["records"][rdtype] = _query_type(resolver, domain, rdtype)

    # TXT / SPF / DMARC policy
    out["txt_policy"] = _extract_spf(out["records"].get("TXT"), domain, resolver)

    # ── Reverse DNS for the first few A addresses ──
    ptrs = {}
    if a_ok:
        for ip in [r["value"] for r in primary["A"]["records"][:MAX_PTR_PROBES]]:
            ptrs[ip] = _reverse_query(resolver, ip)
    if ptrs:
        out["records"]["PTR"] = ptrs
    hostnames = []
    for _ip, block in ptrs.items():
        for rec in block.get("records", []):
            hostnames.append(rec["value"])
    out["reverse"] = {
        "queried_ips": list(ptrs.keys()),
        "hostnames": hostnames,
        "any_found": any(b.get("status") == "OK" for b in ptrs.values()),
    }

    # ── DNSSEC (signed zone lives at the registered domain) ──
    out["dnssec"] = _dnssec_status(resolver, apex)

    # ── Wildcard probe (wildcards are defined at the registered domain) ──
    out["wildcard"] = _wildcard_probe(resolver, apex)

    out["total_time_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    return out

