"""
backend/dns_lookup/scorer.py — Transparent DNS security scoring

Computes the DNS Security Score (0–100, higher is better), a risk level,
findings, warnings and recommendations — strictly from the actual lookup
results produced by resolver.resolve_all(). No fabricated data: every
finding cites the record evidence it was derived from.

Weights (max 100):
    resolution            +20   (A / AAAA / CNAME resolves)
    ipv6 (AAAA)           +10
    SPF                   +15   (penalised when "+all" detected)
    DMARC                 +10
    MX                    +5
    DNSSEC                +20   (validated or enabled)
    nameserver redundancy +10
    reverse DNS (PTR)     +5
    wildcard DNS          -5    (arbitrary subdomains resolve)
    single nameserver     -7
"""

from typing import Dict, List

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def _finding(severity: str, title: str, detail: str) -> Dict:
    return {"severity": severity, "title": title, "detail": detail}


def score_dns(analysis: Dict) -> Dict:
    """
    Build score / risk level / findings / warnings / recommendations
    from a completed resolver.resolve_all() payload.
    """
    records = analysis.get("records", {}) or {}
    resolution = analysis.get("resolution", {}) or {}
    txt_policy = analysis.get("txt_policy", {}) or {}
    dnssec = analysis.get("dnssec", {}) or {}
    reverse = analysis.get("reverse", {}) or {}
    wildcard = analysis.get("wildcard")

    score = 0
    findings: List[Dict] = []
    warnings: List[str] = []
    recommendations: List[str] = []

    # ── Resolution ──
    resolved = bool(resolution.get("resolved"))
    if resolved:
        score += 20
    else:
        findings.append(_finding(
            "CRITICAL", "Domain does not resolve",
            resolution.get("error") or "No A, AAAA or CNAME records were returned."
        ))
        recommendations.append(
            "The domain is unreachable via DNS. Verify the domain name — if it "
            "is yours, restore the address records with your DNS provider."
        )

    # ── IPv6 ──
    aaaa = records.get("AAAA", {})
    if aaaa.get("status") == "OK":
        score += 10
    elif resolved:
        warnings.append(
            "No AAAA (IPv6) records — the domain is not reachable over IPv6."
        )
        recommendations.append(
            "Publish AAAA records to make the domain reachable over IPv6 networks."
        )

    # ── SPF ──
    spf = txt_policy.get("spf", {}) or {}
    if spf.get("present"):
        score += 15
        if spf.get("all_policy") == "+all":
            score -= 15
            findings.append(_finding(
                "HIGH", "SPF policy allows any server (+all)",
                f"SPF record ends with '+all': {spf.get('record')}"
            ))
            recommendations.append(
                "Replace '+all' in the SPF record with '-all' or '~all' — "
                "'+all' lets anyone send email spoofing this domain."
            )
    elif resolved:
        findings.append(_finding(
            "MEDIUM", "No SPF record",
            "Without a v=spf1 TXT record any mail server can send messages "
            "that appear to come from this domain."
        ))
        recommendations.append(
            "Publish an SPF record (v=spf1) restricting which servers may "
            "send email for this domain."
        )

    # ── DMARC ──
    dmarc = txt_policy.get("dmarc", {}) or {}
    if dmarc.get("present"):
        score += 10
        if dmarc.get("policy") == "none":
            warnings.append(
                "DMARC policy is 'p=none' — suspicious mail is monitored but not rejected."
            )
            recommendations.append(
                "Consider strengthening the DMARC policy (p=quarantine or p=reject)."
            )
    elif resolved:
        findings.append(_finding(
            "MEDIUM", "No DMARC record",
            "No v=dmarc1 record at _dmarc — receivers get no instruction on "
            "how to handle spoofed mail from this domain."
        ))
        recommendations.append(
            "Publish a DMARC record (v=dmarc1) so receivers can handle "
            "spoofed messages from this domain."
        )

    # ── MX ──
    mx = records.get("MX", {})
    if mx.get("status") == "OK":
        score += 5
    elif resolved:
        warnings.append(
            "No MX records — the domain does not receive email directly."
        )

    # ── DNSSEC ──
    sec_status = (dnssec.get("status") or "NOT_ENABLED")
    if sec_status in ("ENABLED", "ENABLED_VALIDATED"):
        score += 20
    elif sec_status == "PARTIAL":
        score += 8
        warnings.append(
            "DNSSEC is partially configured (DS without DNSKEY) — complete "
            "the signing chain."
        )
    elif resolved:
        findings.append(_finding(
            "MEDIUM", "DNSSEC is not enabled",
            "DNS responses for this domain are not cryptographically signed, "
            "so they can be forged in cache-poisoning attacks."
        ))
        recommendations.append(
            "Enable DNSSEC at your registrar and DNS provider to sign the zone."
        )

    # ── Nameserver redundancy ──
    ns = records.get("NS", {})
    ns_count = ns.get("count", 0) if ns.get("status") == "OK" else 0
    if ns_count >= 2:
        score += 10
    elif ns_count == 1:
        score -= 4
        findings.append(_finding(
            "MEDIUM", "Single nameserver",
            f"Only one nameserver ({(ns.get('records') or [{}])[0].get('value', '')}) "
            "answers for this domain — no redundancy if it fails."
        ))
        recommendations.append(
            "Add at least one secondary nameserver for redundancy."
        )
    elif resolved:
        findings.append(_finding(
            "HIGH", "No nameservers resolved",
            "No NS records were returned — resolution depends entirely on "
            "the parent zone's glue."
        ))

    # ── Reverse DNS ──
    if reverse.get("any_found"):
        score += 5
    elif resolved and records.get("A", {}).get("status") == "OK":
        warnings.append(
            "No PTR (reverse DNS) for the A-record addresses — common for "
            "shared hosting, but mail servers often require it."
        )
        recommendations.append(
            "Configure PTR records for the A-record addresses if this domain "
            "sends email."
        )

    # ── Wildcard DNS ──
    if wildcard is True:
        score -= 5
        findings.append(_finding(
            "LOW", "Wildcard DNS is active",
            "Random subdomains resolve — wildcard records can be abused for "
            "phishing subdomains and cache pollution."
        ))
        recommendations.append(
            "Remove the wildcard record unless it is intentionally required."
        )

    score = max(0, min(100, score))

    # ── Record-type errors worth surfacing ──
    for _rdtype, block in records.items():
        if isinstance(block, dict) and block.get("status") == "ERROR":
            warnings.append(f"{_rdtype} query failed: {block.get('error')}")

    # ── Risk level ──
    if score >= 75:
        risk = "LOW"
    elif score >= 50:
        risk = "MEDIUM"
    elif score >= 25:
        risk = "HIGH"
    else:
        risk = "CRITICAL"

    summary_checks = _build_checks(analysis)

    return {
        "score": score,
        "risk_level": risk,
        "risk_level_label": risk,
        "findings": sorted(findings, key=lambda f: SEVERITY_ORDER.get(f["severity"], 9)),
        "warnings": warnings,
        "recommendations": recommendations,
        "summary_checks": summary_checks,
    }


def _build_checks(analysis: Dict) -> List[Dict]:
    """Checklist rows for the dashboard panel (like the URL Analyzer's)."""
    records = analysis.get("records", {}) or {}
    txt_policy = analysis.get("txt_policy", {}) or {}
    dnssec = analysis.get("dnssec", {}) or {}

    def st(status):
        return {"OK": "pass", "ERROR": "fail"}.get(status, "skip")

    checks = []
    res = analysis.get("resolution", {})
    checks.append({
        "name": "Domain resolves",
        "status": "pass" if res.get("resolved") else "fail",
        "detail": (", ".join((res.get("ips") or [])[:2]) or res.get("error") or ""),
    })
    for rdtype, label in (("A", "IPv4 (A)"), ("AAAA", "IPv6 (AAAA)"),
                          ("MX", "Mail (MX)"), ("NS", "Nameservers (NS)"),
                          ("SOA", "Zone authority (SOA)"), ("TXT", "Text records (TXT)")):
        b = records.get(rdtype, {})
        checks.append({
            "name": label,
            "status": st(b.get("status")),
            "detail": (f"{b.get('count', 0)} record(s)"
                       if b.get("status") == "OK" else (b.get("error") or "not present")),
        })
    spf = txt_policy.get("spf", {})
    checks.append({"name": "SPF", "status": "pass" if spf.get("present") else "warn",
                   "detail": ((spf.get("record") or "no v=spf1 record")[:60])})
    dmarc = txt_policy.get("dmarc", {})
    checks.append({"name": "DMARC", "status": "pass" if dmarc.get("present") else "warn",
                   "detail": ((dmarc.get("record") or "no v=dmarc1 record")[:60])})
    sec_status = dnssec.get("status") or "NOT_ENABLED"
    checks.append({
        "name": "DNSSEC",
        "status": ("pass" if sec_status.startswith("ENABLED")
                   else "warn" if sec_status == "PARTIAL" else "fail"),
        "detail": sec_status.replace("_", " ").title(),
    })
    rev = analysis.get("reverse", {})
    checks.append({"name": "Reverse DNS (PTR)",
                   "status": "pass" if rev.get("any_found") else "warn",
                   "detail": (rev.get("hostnames") or ["no PTR"])[0]})
    return checks


def build_recommendation(score: int, risk: str, recommendations: List[str]) -> str:
    """Combined recommendation paragraph for the panel + report."""
    if not recommendations:
        if risk == "LOW":
            return ("DNS configuration looks healthy. Records are consistent "
                    f"and the domain scored {score}/100. Re-check periodically.")
        return ("No corrective actions required. DNS posture is acceptable "
                f"with a score of {score}/100.")
    head = {
        "CRITICAL": "This domain has serious DNS problems that must be fixed.",
        "HIGH": "Several DNS issues need attention.",
        "MEDIUM": "The DNS configuration can be improved.",
        "LOW": "Minor DNS improvements are suggested.",
    }.get(risk, "DNS review recommended.")
    return head + " Recommended actions:\n• " + "\n• ".join(recommendations)
