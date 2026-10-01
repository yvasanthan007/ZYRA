"""
backend/url_analyzer/risk_scorer.py — Transparent risk scoring

Converts the collected findings + context into:

    score           — safety score 0..100 (higher = safer)
    risk_level      — CRITICAL | HIGH | MEDIUM | LOW_MEDIUM | LOW
    classification  — MALICIOUS | SUSPICIOUS | LIKELY_SAFE | UNKNOWN
    reasoning       — exact per-finding deductions and caps, so the UI can
                      always show WHY the score was calculated

Design rule: a URL is NEVER reported as definitely safe just because no
indicators were found. When reputation or domain data is unavailable the
score is capped and the wording stays "Likely Safe" / "Unable to
Determine".
"""

RISK_LEVEL_LABELS = {
    "LOW": "LOW",
    "LOW_MEDIUM": "LOW-MEDIUM",
    "MEDIUM": "MEDIUM",
    "HIGH": "HIGH",
    "CRITICAL": "CRITICAL",
}

CLASSIFICATION_LABELS = {
    "LIKELY_SAFE": "LIKELY SAFE",
    "SUSPICIOUS": "SUSPICIOUS",
    "MALICIOUS": "MALICIOUS",
    "UNKNOWN": "UNKNOWN",
}

CLASSIFICATION_SUMMARY = {
    "LIKELY_SAFE": "Likely Safe",
    "SUSPICIOUS": "Suspicious",
    "MALICIOUS": "Malicious Indicators Detected",
    "UNKNOWN": "Unable to Determine",
}

# Score caps when external verification is missing — a URL can never look
# 100% safe without threat-intelligence / domain confirmation.
CAP_NO_REPUTATION = 92
CAP_NO_DOMAIN_INFO = 95
BASE_SCORE = 100


def _risk_level(score: int) -> str:
    if score >= 90:
        return "LOW"
    if score >= 70:
        return "LOW_MEDIUM"
    if score >= 40:
        return "MEDIUM"
    if score >= 20:
        return "HIGH"
    return "CRITICAL"


def score_scan(findings: list, domain_info: dict = None,
               ssl_info: dict = None, reputation: dict = None,
               ml_analysis: dict = None) -> dict:
    """
    Compute the transparent safety score.

    ml_analysis: predictor.analyze_url_ml() payload (optional). The ML
    classifier can only LOWER the score / raise the classification — it
    never makes a flagged URL look safer.

    Returns {score, risk_level, risk_level_label, classification,
             classification_label, classification_summary, reasoning}.
    """
    reasoning = []
    score = BASE_SCORE
    reasoning.append(f"Base score: {BASE_SCORE}")

    has_critical = False
    has_high = False

    for f in findings or []:
        impact = int(f.get("score_impact") or 0)
        if impact <= 0:
            continue
        score = max(0, score - impact)
        reasoning.append(
            f"-{impact} {f.get('severity', '?')}: {f.get('title', 'finding')}"
        )
        if f.get("severity") == "CRITICAL":
            has_critical = True
        elif f.get("severity") == "HIGH":
            has_high = True

    reputation = reputation or {}
    domain_info = domain_info or {}
    reputation_available = bool(reputation.get("available"))
    domain_resolved = bool(domain_info.get("resolved"))

    # Nothing verifiable at all → Unable to Determine
    nothing_verified = (
        not domain_resolved
        and ssl_info is not None and not ssl_info.get("checked")
        and not reputation_available
    )

    # Transparency caps
    if not reputation_available and score > CAP_NO_REPUTATION:
        score = CAP_NO_REPUTATION
        reasoning.append(
            f"Score capped at {CAP_NO_REPUTATION}: reputation data "
            f"unavailable, safety cannot be fully verified."
        )
    if not domain_info.get("whois_available") and score > CAP_NO_DOMAIN_INFO:
        score = CAP_NO_DOMAIN_INFO
        reasoning.append(
            f"Score capped at {CAP_NO_DOMAIN_INFO}: domain registration "
            f"information could not be verified."
        )

    score = max(0, min(100, int(score)))

    # ── Classification ──
    rep_malicious = (
        reputation_available
        and str(reputation.get("reputation", "")).lower() == "malicious"
    )

    if rep_malicious or has_critical or score < 20:
        classification = "MALICIOUS"
    elif nothing_verified:
        classification = "UNKNOWN"
    elif has_high or score < 70:
        classification = "SUSPICIOUS"
    else:
        classification = "LIKELY_SAFE"

    # reputation-malicious forces the score into the malicious band
    if rep_malicious and score >= 20:
        score = min(score, 18)
        reasoning.append(
            "Score capped at 18: threat intelligence reported malicious activity."
        )

    # ── ML phishing classifier: probabilistic floor / cap ──
    # Tiers match predictor.py _VERDICT_TIERS: >=0.90 forces MALICIOUS with a
    # hard score cap; >=0.75 raises a clean/unknown URL to SUSPICIOUS; lower
    # probabilities only add a reasoning line (advisory).
    ml_available = bool(ml_analysis and ml_analysis.get("available"))
    ml_prob = 0.0
    if ml_available:
        try:
            ml_prob = float(ml_analysis.get("probability") or 0.0)
        except (TypeError, ValueError):
            ml_prob = 0.0
    if ml_available and ml_prob >= 0.55:
        algo = ml_analysis.get("algorithm") or "ML classifier"
        reasoning.append(
            f"ML phishing classifier ({algo}) estimated a "
            f"{int(round(ml_prob * 100))}% phishing probability from URL structure."
        )
    if ml_available and ml_prob >= 0.90:
        classification = "MALICIOUS"
        if score > 15:
            score = 15
            reasoning.append(
                "Score capped at 15: ML classifier reports very high phishing "
                "probability."
            )
    elif ml_available and ml_prob >= 0.75 and classification in ("LIKELY_SAFE", "UNKNOWN"):
        classification = "SUSPICIOUS"
        reasoning.append(
            "Classification raised to SUSPICIOUS by the ML phishing classifier."
        )

    score = max(0, min(100, int(score)))
    risk = _risk_level(score)
    return {
        "score": score,
        "risk_level": risk,
        "risk_level_label": RISK_LEVEL_LABELS.get(risk, risk),
        "classification": classification,
        "classification_label": CLASSIFICATION_LABELS[classification],
        "classification_summary": CLASSIFICATION_SUMMARY[classification],
        "reasoning": reasoning,
    }


def build_recommendation(classification: str, findings: list,
                         reputation: dict = None) -> str:
    """Final human-readable recommendation per classification."""
    reputation = reputation or {}
    rep_available = bool(reputation.get("available"))

    if classification == "MALICIOUS":
        return (
            "Malicious indicators were detected. Do NOT open this URL, do not "
            "enter credentials or personal information, and report the source "
            "of the link."
        )
    if classification == "SUSPICIOUS":
        return (
            "Several suspicious indicators were detected. Avoid entering "
            "credentials or sensitive information; verify the destination "
            "through an independent, trusted channel first."
        )
    if classification == "UNKNOWN":
        return (
            "Insufficient information to confidently classify this URL. The "
            "target could not be reliably reached or verified — proceed with "
            "extreme caution or avoid it entirely."
        )
    # LIKELY_SAFE
    if not rep_available:
        return (
            "No significant malicious indicators were detected, but reputation "
            "data was unavailable during this scan. Users should still verify "
            "the destination before entering credentials or sensitive "
            "information."
        )
    return (
        "No significant malicious indicators were detected, but users should "
        "still verify the destination before entering credentials or "
        "sensitive information."
    )
