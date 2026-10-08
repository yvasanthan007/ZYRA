#!/usr/bin/env python3
"""
tools/ml_eval.py — Controlled evaluation of ZYRA's ML phishing pipeline.

For every URL in the controlled set (clearly safe / clearly suspicious) it prints:

    URL | EXPECTED | PREDICTED | PROBABILITY | RISK SCORE | RISK LEVEL | KEY FEATURES

and computes accuracy, precision, recall, F1 and the confusion matrix for:

  (a) the raw ML predictor   (backend/ml_phishing/predictor.analyze_url)
  (b) the full scan path     (risk_scorer.score_scan with ML attached)

Run:  .venv\\Scripts\\python.exe tools/ml_eval.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.ml_phishing import predictor                      # noqa: E402
from backend.ml_phishing.features import extract_features      # noqa: E402
from backend.url_analyzer.risk_scorer import score_scan        # noqa: E402

# label 1 = phishing, 0 = legitimate (same convention as dataset.py)
EVAL_SET = [
    # ── clearly safe ──
    ("https://www.google.com/search?q=python+tutorial", 0),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", 0),
    ("https://github.com/torvalds/linux", 0),
    ("https://en.wikipedia.org/wiki/Phishing", 0),
    ("https://www.amazon.com/dp/B08N5WRWNW", 0),
    ("https://mail.google.com/mail/u/0/#inbox", 0),
    ("https://www.linkedin.com/feed/", 0),
    ("https://stackoverflow.com/questions/tagged/python", 0),
    ("https://www.microsoft.com/en-us/download/", 0),
    ("https://www.reddit.com/r/programming/", 0),
    # ── clearly suspicious / phishing ──
    ("http://paypa1-secure-login.verify-account-now.xyz/login.php?token=a1b2c3d4e5f60718", 1),
    ("http://192.168.13.37/paypal/login.php?user=test&pass=secret123", 1),
    ("https://paypal.com.verify-suspension-4821.tk/account/verify?token=ff0099aabb001122", 1),
    ("http://apple-id-unlock.verification-required.ml/reset?pw=abc123", 1),
    ("https://login-verify-amazon.secure-account.xyz/signin?email=a%40b.com&pwd=q1w2e3", 1),
    ("http://free-crypto-giveaway-urgent.claim-now.top/walletconnect?addr=0xdeadbeef", 1),
    ("https://facebook-security-alert.account-locked.tk/confirm?next=login%2Fverify", 1),
    ("http://update-your-password-immediately.userverify.tk/auth?id=998877", 1),
    ("https://netflix.billing-update-required.xyz/pay?card=4111111111111111", 1),
    ("http://microsoft-verify-account.urgent-action.ml/login/live.com?cid=12345", 1),
    # ── HARD: legitimate URLs engineered to look suspicious to a lexical model
    #     (long random query tokens, hex-ish path segments, non-https, IP host,
    #      'login' wording, url shorteners, embedded credentials in docs links) ──
    ("http://neverssl.com", 0),
    ("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=00000000-0000-0000-0000-000000000000&response_type=code&redirect_uri=https%3A%2F%2Fportal.azure.com%2Fsignin%2Findex%2F&scope=https%3A%2F%2Fmanagement.azure.com%2F.default", 0),
    ("https://github.com/user/repo/commit/9f8e7d6c5b4a39281706f5e4d3c2b1a098765432", 0),
    ("https://accounts.google.com/signin/v2/identifier?service=mail&continue=https%3A%2F%2Fmail.google.com%2Fmail%2F&flowName=GlifWebSignIn&flowEntry=ServiceLogin", 0),
    ("https://www.youtube.com/results?search_query=how+to+phish+people+for+science", 0),
    ("https://bit.ly/3nKx2pQ", 0),
    ("https://t.co/8HgYQ1kL2m", 0),
    ("http://192.168.1.1/admin/login.php", 0),
    ("https://example.com/reset-password?token=abcdef1234567890abcdef1234567890&email=user%40example.com", 0),
    ("https://www.twitch.tv/directory/category/just-chatting", 0),
    # ── HARD: realistic subtle phishing (no obvious junk TLD, https, brand look) ──
    ("https://www.paypal-secure.account-verification.info/signin?redirect=url.com", 1),
    ("https://apple-support.verify-your-id.com/reset", 1),
    ("https://g00gle.com/mail/u/0/", 1),
    ("https://www.amaz0n-security.com/login", 1),
    ("https://secure-login.xyz/bank/auth", 1),
    ("https://walletconnect-claim.live/airdrop?address=0xAbC123", 1),
    ("http://bit.ly/2XyZ-phish-credential", 1),
    ("https://instagram.com.login-check.top/session", 1),
]


def key_features(url, top=4):
    feats = extract_features(url)
    interesting = ["suspicious_tld", "credential_keywords", "urgency_keywords",
                   "brand_misplaced", "has_ip_host", "is_https", "num_subdomains",
                   "digit_ratio_host", "is_shortener", "has_userinfo_trick"]
    out = []
    for name in interesting:
        v = feats.get(name)
        if v:
            out.append(f"{name}={v}")
    return ", ".join(out[:top]) or "(none flagged)"


def pct(x):
    return f"{x * 100:.1f}%" if isinstance(x, float) else str(x)


def metrics(y_true, y_pred):
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    acc = (tp + tn) / max(1, len(y_true))
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    f1 = 2 * prec * rec / max(1e-9, prec + rec)
    return dict(accuracy=acc, precision=prec, recall=rec, f1=f1,
                confusion=dict(tn=tn, fp=fp, fn=fn, tp=tp))


def main():
    print("=" * 110)
    print("ZYRA ML PHISHING — CONTROLLED EVALUATION")
    print("=" * 110)

    # (a) ML-only predictor
    y_true, y_pred, rows = [], [], []
    print("\n--- (a) ML predictor: analyze_url_ml() ---")
    print(f"{'URL':<72}{'EXP':>4}{'PRD':>5}{'PROB':>8}{'VERDICT':>17}")
    for url, expected in EVAL_SET:
        res = predictor.analyze_url(url)
        prob = res.get("probability")
        verdict = res.get("verdict", "n/a") if res.get("available") else "UNAVAILABLE"
        pred = 1 if (res.get("available") and prob is not None and prob >= 0.5) else 0
        y_true.append(expected)
        y_pred.append(pred)
        rows.append((url, expected, pred, prob, verdict, res))
        print(f"{url:<72}{expected:>4}{pred:>5}"
              f"{pct(prob) if prob is not None else 'n/a':>8}{verdict:>17}")

    m = metrics(y_true, y_pred)
    print(f"\nML-ONLY  accuracy={m['accuracy']:.3f}  precision={m['precision']:.3f}  "
          f"recall={m['recall']:.3f}  f1={m['f1']:.3f}")
    c = m["confusion"]
    print(f"confusion matrix: TN={c['tn']} FP={c['fp']} FN={c['fn']} TP={c['tp']}")

    # (b) full scan path: score_scan with the ML payload attached (findings=[]
    # isolates the ML->risk mapping layer; no network lookups)
    print("\n--- (b) risk_scorer.score_scan(findings=[], ml_analysis=result) ---")
    print(f"{'URL':<72}{'EXP':>4}{'SCORE':>7}{'RISK':>10}{'CLASS':>15}")
    y2_true, y2_pred = [], []
    for url, expected, pred, prob, verdict, res in rows:
        scored = score_scan([], ml_analysis=res if res.get("available") else None)
        cls = scored["classification"]
        pred2 = 1 if cls in ("MALICIOUS", "SUSPICIOUS") else 0
        y2_true.append(expected)
        y2_pred.append(pred2)
        print(f"{url:<72}{expected:>4}{scored['score']:>7}"
              f"{scored['risk_level']:>10}{cls:>15}")

    m2 = metrics(y2_true, y2_pred)
    print(f"\nSCAN-PATH accuracy={m2['accuracy']:.3f}  precision={m2['precision']:.3f}  "
          f"recall={m2['recall']:.3f}  f1={m2['f1']:.3f}")
    c2 = m2["confusion"]
    print(f"confusion matrix: TN={c2['tn']} FP={c2['fp']} FN={c2['fn']} TP={c2['tp']}")

    # per-row detail: features + score/risk for the record
    print("\n--- detail (features + risk) ---")
    for url, expected, pred, prob, verdict, res in rows:
        scored = score_scan([], ml_analysis=res if res.get("available") else None)
        print(f"\nURL      : {url}\nEXPECTED : {'PHISHING' if expected else 'SAFE'}"
              f"\nPREDICTED: {'PHISHING' if pred else 'SAFE'}  ({verdict}, prob={pct(prob)})"
              f"\nRISK     : score={scored['score']} level={scored['risk_level']} "
              f"class={scored['classification']}"
              f"\nFEATURES : {key_features(url)}")

    bad = [r for r in rows if r[1] != r[2]]
    print(f"\nML-ONLY wrong predictions: {len(bad)}/{len(rows)}")
    for url, expected, pred, prob, verdict, _ in bad:
        print(f"  MISCLASSIFIED exp={expected} pred={pred} prob={pct(prob)} {verdict} {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
