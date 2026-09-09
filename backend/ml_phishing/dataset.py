"""
backend/ml_phishing/dataset.py — Training data for ZYRA's ML phishing
classifier.

Two data sources:

1. SEED dataset (default) — generated deterministically (seeded RNG) from
   realistic URL patterns: popular legitimate sites with normal paths vs.
   known phishing lure patterns (typosquatting, brand-in-subdomain, raw IP
   hosts, shortener lures, punycode, '@' tricks, urgency bait, ...).
   It is pattern-based, so it teaches the model the same signal space the
   heuristic engine covers — but with learned, probabilistic weights.

2. EXTERNAL CSV (recommended for production) — pass --csv to the trainer
   with a real dataset (e.g. a PhishTank + Tranco export) formatted as:

       url,label
       http://...,phishing
       https://...,legitimate

   Accepted phishing label spellings: phishing / phish / bad / malicious /
   1 / true / yes / y / spam — anything else counts as legitimate.
"""

import csv
import random
import string

# ──────────────────────────────────────────────
# Legitimate seed: real popular domains, realistic normal paths
# ──────────────────────────────────────────────

_LEGIT_SITES = [
    ("google.com", ["/search", "/maps", "/mail", "/drive", "/calendar", ""]),
    ("youtube.com", ["/watch?v=dQw4w9WgXcQ", "/feed/subscriptions",
                     "/playlist?list=PL123456", "/results?search_query=python"]),
    ("facebook.com", ["/profile.php?id=100012345678", "/groups/12345678",
                      "/marketplace", "/watch", "/login"]),
    ("instagram.com", ["/explore", "/reels", "/accounts/login", "/stories/highlights"]),
    ("amazon.com", ["/dp/B08N5WRWNW", "/s?k=laptop", "/gp/cart/view.html",
                    "/prime", "/your-orders", "/gp/help/customer/display.html"]),
    ("wikipedia.org", ["/wiki/Machine_learning", "/wiki/Phishing",
                       "/wiki/Python_(programming_language)", "/wiki/URL"]),
    ("netflix.com", ["/browse", "/watch/812934", "/search?q=comedy"]),
    ("microsoft.com", ["/en-us/software-download", "/windows",
                       "/microsoft-365", "/security"]),
    ("apple.com", ["/iphone", "/mac", "/support", "/apple-music"]),
    ("github.com", ["/topics/machine-learning", "/pulls", "/settings/profile",
                    "/explore", "/features/security"]),
    ("paypal.com", ["/signin", "/myaccount/summary", "/smart/connect", "/welcome/"]),
    ("chase.com", ["/personal/banking", "/credit-cards", "/auto-loans"]),
    ("coinbase.com", ["/portfolio", "/prices", "/accounts"]),
    ("linkedin.com", ["/feed", "/jobs", "/mynetwork", "/learning"]),
    ("reddit.com", ["/r/programming", "/r/netsec/top/?t=week", "/settings",
                    "/r/MachineLearning"]),
    ("stackoverflow.com", ["/questions/tagged/python", "/users/1234/dev", "/jobs"]),
    ("dropbox.com", ["/home", "/sharing/content", "/plans"]),
    ("spotify.com", ["/playlist/37i9dQZF1DXcBWIGoYBM5M", "/search/taylor%20swift",
                     "/genre/discover-page"]),
    ("steampowered.com", ["/app/570/Dota_2", "/login/home", "/sale/summer"]),
    ("roblox.com", ["/games", "/discover", "/upgrades/robux"]),
    ("discord.com", ["/channels/@me", "/download", "/guild-discovery"]),
    ("zoom.us", ["/join", "/meetings", "/pricing"]),
    ("office.com", ["/docs", "/launch/excel", "/templates"]),
    ("outlook.live.com", ["/mail/0/inbox", "/owa/", "/calendar/0/view/month"]),
    ("yahoo.com", ["/news", "/finance", "/mail", "/sports"]),
    ("ebay.com", ["/sch/i.html?_nkw=camera", "/itm/123456789012", "/myebay"]),
    ("nytimes.com", ["/2024/05/01/technology/", "/section/technology", "/opinion"]),
    ("bbc.co.uk", ["/news/technology-68901234", "/sport/football", "/weather"]),
    ("cnn.com", ["/2024/05/01/tech/", "/world/live-news", "/business"]),
    ("irs.gov", ["/payments/direct-debit", "/refunds", "/forms-pubs"]),
    ("gov.uk", ["/check-uk-visa", "/report-suspicious-emails-and-phishing", "/tax"]),
    ("python.org", ["/downloads/", "/doc/", "/3/whatsnew/3.12.html", "/psf/"]),
    ("mozilla.org", ["/en-US/firefox/new/", "/en-US/products/vpn/"]),
    ("ubuntu.com", ["/download/desktop", "/server", "/blog"]),
    ("cloudflare.com", ["/learning/security/what-is-phishing/", "/plans/"]),
    ("dhl.com", ["/en/express/tracking.html", "/global/en/home.html"]),
    ("fedex.com", ["/en-us/tracking.html", "/en-us/home.html"]),
    ("usps.com", ["/business/web-tools-api/track-and-confirm-api.htm", "/tracking"]),
    ("harvard.edu", ["/admissions", "/academics", "/research"]),
    ("mit.edu", ["/academics", "/research", "/admissions-aid"]),
    ("wellsfargo.com", ["/checking-account/", "/online-banking/", "/mortgage/"]),
    ("binance.com", ["/en/markets/overview", "/en/my/wallet/account/main",
                     "/en/trade/BTC_USDT"]),
    ("x.com", ["/home", "/i/lists/123456", "/settings", "/search?q=ai"]),
]

_LEGIT_SUBDOMAINS = ["", "", "", "", "www.", "www.", "www.", "m.", "mobile.",
                     "blog.", "docs.", "support.", "mail.", "shop.", "accounts.",
                     "play.", "news.", "help."]

_LEGIT_QUERIES = ["", "", "",
                  "?utm_source=google&utm_medium=cpc", "?ref=homepage",
                  "?page=2", "?hl=en", "?id=88421", "?v=2.4.1",
                  "?tab=overview", "?sort=new", "?lang=en-US", "?q=hello+world"]

# ──────────────────────────────────────────────
# Phishing seed: realistic lure-pattern generators
# ──────────────────────────────────────────────

_BAD_TLDS = ["xyz", "top", "tk", "ml", "ga", "cf", "gq", "icu", "cyou", "buzz",
             "click", "link", "work", "rest", "monster", "quest", "cam", "bar",
             "loan", "download", "stream", "fit", "racing", "zip", "mov"]

_BRANDS = ["paypal", "google", "facebook", "amazon", "apple", "microsoft",
           "netflix", "instagram", "whatsapp", "linkedin", "dropbox", "icloud",
           "coinbase", "binance", "steam", "roblox", "outlook", "gmail",
           "yahoo", "dhl", "fedex", "usps", "chase", "wellsfargo", "office365"]

_DIGIT_MAP = str.maketrans({"o": "0", "i": "1", "l": "1", "e": "3",
                            "a": "4", "s": "5", "t": "7", "b": "8"})

_CRED_PATHS = ["/login.php", "/signin", "/verify/account", "/account/verify",
               "/secure/login.html", "/update-billing", "/payment/confirm",
               "/wp-login.php", "/unlock-account", "/recover/password",
               "/2fa/verify", "/billing/update.php", "/banking/login",
               "/wallet/confirm", "/sessions/token", "/auth/validate"]

_URGENCY_WORDS = ["urgent", "suspended", "alert", "limited", "verify-now",
                  "act-now", "warning", "unlock", "prize", "winner", "claim",
                  "bonus", "recovery", "final-notice"]

_NEUTRAL_HOST_WORDS = ["secure", "login", "account", "verify", "update",
                       "service", "support", "auth", "myaccount", "signin",
                       "billing", "wallet", "recovery", "online", "client",
                       "helpdesk", "confirmation"]

_PHISH_SCHEMES = ["http", "http", "https", "https", "https"]

_SHORTENERS = ["bit.ly", "tinyurl.com", "cutt.ly", "rb.gy", "shorturl.at",
               "is.gd", "ow.ly", "t.ly"]


def _random_hex(rng, n=8):
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


def _random_token(rng, n=10):
    return "".join(rng.choice(string.ascii_letters + string.digits)
                   for _ in range(n))


def _brand_variants(brand, rng):
    """Typosquat / lookalike variants of a brand name."""
    variants = []
    for i, ch in enumerate(brand):
        if ch in "oilaeastb":
            variants.append(brand[:i] + ch.translate(_DIGIT_MAP) + brand[i + 1:])
    variants.append(brand + "-secure")
    variants.append("secure-" + brand)
    variants.append(brand + "-login")
    variants.append(brand + "s")
    if len(brand) > 4:
        i = rng.randrange(1, len(brand) - 1)
        variants.append(brand[:i] + "-" + brand[i:])
        variants.append(brand[:i] + brand[i + 1:])            # dropped letter
        variants.append(brand[:i] + brand[i] + brand[i:])     # doubled letter
    return variants or [brand]

def _phish_url(rng):
    """Build one realistic phishing lure URL from a random pattern family."""
    brand = rng.choice(_BRANDS)
    tld = rng.choice(_BAD_TLDS)
    variant = rng.choice(_brand_variants(brand, rng))
    scheme = rng.choice(_PHISH_SCHEMES)
    cred = rng.choice(_CRED_PATHS)
    q = rng.choice(["", f"?token={_random_hex(rng)}",
                    f"?session={_random_hex(rng, 12)}",
                    f"?redirect={brand}%2Flogin",
                    f"?email=user{_random_hex(rng, 4)}%40mail.com",
                    f"?code={_random_token(rng, 8)}"])

    kind = rng.choices(
        ["typo_tld", "brand_subdomain", "ip_host", "shortener", "punycode",
         "at_trick", "encoded", "sub_bury", "prize", "php_random",
         "hex_dir", "hyphen_chain"],
        weights=[22, 18, 10, 8, 5, 6, 7, 10, 5, 5, 2, 2])[0]

    if kind == "typo_tld":
        host = f"{variant}{'-' + rng.choice(_NEUTRAL_HOST_WORDS) if rng.random() < 0.4 else ''}.{tld}"
    elif kind == "brand_subdomain":
        base = f"{rng.choice(_NEUTRAL_HOST_WORDS)}-{_random_hex(rng, 4)}"
        host = f"{brand}.com.{base}.{tld}"
    elif kind == "ip_host":
        host = (f"{rng.randrange(11, 223)}.{rng.randrange(0, 256)}."
                f"{rng.randrange(0, 256)}.{rng.randrange(1, 255)}")
    elif kind == "shortener":
        sh = rng.choice(_SHORTENERS)
        if rng.random() < 0.6:
            alias = f"{rng.choice(_URGENCY_WORDS)}-{_random_token(rng, 4)}"
        else:
            alias = _random_token(rng, 7)
        return f"{scheme}://{sh}/{alias}{q}"
    elif kind == "punycode":
        host = rng.choice(["xn--pple-43d.com", "xn--paypa-2ve.com",
                           f"xn--{variant}-{_random_token(rng, 3).lower()}.{tld}"])
    elif kind == "at_trick":
        evil = f"{variant}-{rng.choice(_NEUTRAL_HOST_WORDS)}.{tld}"
        return f"https://{brand}.com@{evil}{cred}{q}"
    elif kind == "encoded":
        enc = "".join("%" + c for c in rng.choice(["verify", "account", "login"]))
        host = f"{variant}.{tld}"
        return f"{scheme}://{host}/{enc}{q}"
    elif kind == "sub_bury":
        w1 = rng.choice(_NEUTRAL_HOST_WORDS)
        w2 = rng.choice(_NEUTRAL_HOST_WORDS)
        host = f"{brand}.login.{w1}{_random_hex(rng, 2)}.{w2}.{tld}"
    elif kind == "prize":
        host = f"{rng.choice(['free-gift', 'prize-winner', 'claim-bonus', 'cash-reward'])}-{_random_hex(rng, 3)}.{tld}"
        cred = "/claim"
    elif kind == "php_random":
        host = f"{rng.choice(_NEUTRAL_HOST_WORDS)}-{_random_hex(rng, 3)}.{tld}"
        cred = rng.choice(["/wp-content/uploads/2024/login.html",
                           "/user/login.php", "/index.php?option=com_login",
                           "/auth.php"])
    elif kind == "hex_dir":
        host = f"{variant}-secure.{tld}"
        cred = f"/{_random_hex(rng, 20)}/verify.php"
    else:  # hyphen_chain
        host = f"{'-'.join(rng.sample(_NEUTRAL_HOST_WORDS, 3))}-{_random_hex(rng, 2)}.{tld}"

    return f"{scheme}://{host}{cred}{q}"


def _legit_url(rng):
    """Build one realistic legitimate URL (popular site, normal path)."""
    domain, paths = rng.choice(_LEGIT_SITES)
    scheme = "https" if rng.random() > 0.03 else "http"
    # Occasional legitimate marketing-shortener use (random aliases only)
    if rng.random() < 0.04:
        sh = rng.choice(["bit.ly", "tinyurl.com", "ow.ly", "is.gd"])
        return f"{scheme}://{sh}/{_random_token(rng, rng.choice([6, 7, 8]))}"
    sub = rng.choice(_LEGIT_SUBDOMAINS)
    path = rng.choice(paths)
    q = rng.choice(_LEGIT_QUERIES)
    return f"{scheme}://{sub}{domain}{path}{q}"

# ──────────────────────────────────────────────
# Dataset assembly
# ──────────────────────────────────────────────

def seed_dataset(per_class=1200, seed=42):
    """
    Deterministic seed dataset. Returns (urls, labels) with label 1 = phishing,
    0 = legitimate. Generation is seeded, so retraining reproduces the data.
    """
    rng = random.Random(seed)
    urls, labels = [], []
    seen = set()
    attempts = 0
    n_legit = n_phish = 0
    while (n_legit < per_class or n_phish < per_class) and attempts < per_class * 20:
        attempts += 1
        if n_legit < per_class and (n_phish >= per_class or rng.random() < 0.5):
            u = _legit_url(rng)
            if u in seen:
                continue
            seen.add(u)
            urls.append(u)
            labels.append(0)
            n_legit += 1
        elif n_phish < per_class:
            u = _phish_url(rng)
            if u in seen:
                continue
            seen.add(u)
            urls.append(u)
            labels.append(1)
            n_phish += 1
    return urls, labels


def load_csv(path):
    """
    Load an external labeled dataset:  url,label  (header optional).
    Returns (urls, labels) with 1 = phishing, 0 = legitimate.
    """
    import os

    urls, labels = [], []
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        first = sample.splitlines()[0].lower() if sample.splitlines() else ""
        has_header = any(k in first for k in ("url", "label", "class", "type"))
        reader = csv.reader(fh)
        rows = list(reader)
    if has_header and rows:
        rows = rows[1:]
    phishing_labels = {"phishing", "phish", "bad", "malicious", "1", "true",
                       "yes", "y", "spam"}
    for row in rows:
        if not row or len(row) < 2:
            continue
        url = (row[0] or "").strip()
        label = (row[1] or "").strip().lower()
        if not url:
            continue
        urls.append(url)
        labels.append(1 if label in phishing_labels else 0)
    if not urls:
        raise ValueError(f"dataset CSV '{os.path.basename(path)}' had no usable url,label rows")
    return urls, labels


def build_dataset(csv_path=None, per_class=1200, seed=42):
    """
    External CSV wins when provided; otherwise the deterministic seed dataset.
    Returns (urls, labels, stats_dict).
    """
    import os

    if csv_path:
        urls, labels = load_csv(csv_path)
        stats = {
            "source": os.path.basename(csv_path),
            "size": len(urls),
            "phishing": int(sum(labels)),
            "legitimate": int(len(labels) - sum(labels)),
        }
        return urls, labels, stats
    urls, labels = seed_dataset(per_class=per_class, seed=seed)
    stats = {
        "source": "builtin-seed-dataset",
        "size": len(urls),
        "phishing": int(sum(labels)),
        "legitimate": int(len(labels) - sum(labels)),
    }
    return urls, labels, stats





