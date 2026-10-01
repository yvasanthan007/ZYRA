"""
backend/ml_phishing/predictor.py — Inference for ZYRA's ML phishing
classifier.

Loads the trained model lazily (thread-safe) and exposes analyze_url_ml():
a dict with the phishing probability, a verdict, and the most influential
features for this URL (flagged features ranked by model importance).

Degradation contract (matches ZYRA's backend style — never raises):
  - scikit-learn / joblib missing or model file missing → {"available": False}
  - ZYRA_ML_DISABLE=1                                   → disabled at runtime
  - ZYRA_ML_MODEL=/path/model.joblib                    → custom model path
"""

import json
import os
import threading

from backend.ml_phishing.features import (
    FEATURE_DESCRIPTIONS,
    FEATURE_NAMES,
    extract_features,
)

try:
    import joblib
except ImportError:  # sklearn stack absent — heuristic engine still works
    joblib = None

_MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
_DEFAULT_MODEL_PATH = os.path.join(_MODEL_DIR, "phishing_model.joblib")

_LOCK = threading.Lock()
_CACHE = {"key": None, "model": None, "meta": None}


def _model_path():
    override = os.environ.get("ZYRA_ML_MODEL")
    return os.path.abspath(override) if override else _DEFAULT_MODEL_PATH


def _enabled():
    return os.environ.get("ZYRA_ML_DISABLE", "0").strip().lower() not in (
        "1", "true", "yes")


def _load():
    """Lazy, thread-safe model load keyed on path + mtime."""
    path = _model_path()
    try:
        mtime = os.path.getmtime(path) if os.path.exists(path) else None
    except OSError:
        mtime = None
    key = (path, mtime)
    with _LOCK:
        if _CACHE["key"] == key and _CACHE["model"] is not None:
            return _CACHE["model"], _CACHE["meta"]
        model = meta = None
        if joblib is not None and os.path.exists(path):
            try:
                payload = joblib.load(path)
                model = payload.get("model") if isinstance(payload, dict) else payload
                meta_path = os.path.join(os.path.dirname(path), "model_meta.json")
                if os.path.exists(meta_path):
                    with open(meta_path, "r", encoding="utf-8") as fh:
                        meta = json.load(fh)
            except Exception:
                model = meta = None
        _CACHE.update({"key": key, "model": model, "meta": meta})
        return model, meta


def _feature_importances(model, meta):
    """Global importances ranked desc, as [(name, importance), ...]."""
    cached = (meta or {}).get("feature_importances")
    if cached:
        return [(n, float(i)) for n, i in cached]
    importances = None
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    elif hasattr(model, "named_steps"):
        clf = model.named_steps.get("clf")
        if clf is not None and hasattr(clf, "coef_"):
            importances = abs(clf.coef_[0])
    if importances is None:
        return []
    return sorted(zip(FEATURE_NAMES, importances), key=lambda p: -float(p[1]))


def model_info() -> dict:
    """Metadata about the trained model (never raises)."""
    if not _enabled():
        return {"available": False,
                "note": "ML classifier disabled via ZYRA_ML_DISABLE."}
    model, meta = _load()
    if model is None:
        return {"available": False,
                "note": "ML model not trained. Run: python -m backend.ml_phishing.train"}
    return {
        "available": True,
        "model_path": _model_path(),
        "algorithm": (meta or {}).get("algorithm", type(model).__name__),
        "version": (meta or {}).get("version"),
        "trained_at": (meta or {}).get("trained_at"),
        "metrics": (meta or {}).get("metrics"),
        "dataset": (meta or {}).get("dataset"),
        "n_features": len(FEATURE_NAMES),
        "sklearn_version": (meta or {}).get("sklearn_version"),
    }

# Probability → verdict mapping (must match risk_scorer.py's ML floor tiers)
_VERDICT_TIERS = [
    (0.90, "PHISHING"),
    (0.75, "LIKELY_PHISHING"),
    (0.55, "SUSPICIOUS"),
    (0.35, "UNSURE"),
]


def _verdict(prob):
    for threshold, label in _VERDICT_TIERS:
        if prob >= threshold:
            return label
    return "SAFE"


def _risk_band(prob):
    if prob >= 0.90:
        return "CRITICAL"
    if prob >= 0.75:
        return "HIGH"
    if prob >= 0.55:
        return "MEDIUM"
    return "LOW"


def analyze_url(url: str) -> dict:
    """
    ML-only phishing assessment for one URL. Never raises.

    Returns (when the model is available):
        {
          "available": True,
          "url", "algorithm", "model_version",
          "probability": 0.0..1.0   — phishing probability
          "percent":    0..100
          "verdict":    PHISHING | LIKELY_PHISHING | SUSPICIOUS |
                        UNSURE | SAFE
          "risk_band":  CRITICAL | HIGH | MEDIUM | LOW
          "confidence": max(p, 1-p)
          "top_signals": [{feature, value, importance, description}, ...]
          "metrics":    hold-out metrics from training
        }
    """
    try:
        raw = str(url or "").strip()
        if not raw:
            return {"available": False, "note": "Empty URL."}
        if not _enabled():
            return {"available": False,
                    "note": "ML classifier disabled via ZYRA_ML_DISABLE."}
        model, meta = _load()
        if model is None:
            return model_info()  # carries available=False + reason
        feats = extract_features(raw)
        vec = [float(feats.get(name, 0)) for name in FEATURE_NAMES]
        prob = float(model.predict_proba([vec])[0][1])
        prob = min(max(prob, 0.0), 1.0)

        signals = []
        for name, importance in _feature_importances(model, meta):
            value = feats.get(name, 0)
            if value and importance >= 0.02:
                signals.append({
                    "feature": name,
                    "value": value,
                    "importance": round(float(importance), 4),
                    "description": FEATURE_DESCRIPTIONS.get(name, name),
                })
            if len(signals) >= 5:
                break

        return {
            "available": True,
            "url": raw,
            "algorithm": (meta or {}).get("algorithm", type(model).__name__),
            "model_version": (meta or {}).get("version"),
            "probability": round(prob, 4),
            "percent": int(round(prob * 100)),
            "verdict": _verdict(prob),
            "risk_band": _risk_band(prob),
            "confidence": round(max(prob, 1.0 - prob), 4),
            "top_signals": signals,
            "metrics": (meta or {}).get("metrics"),
        }
    except Exception as exc:  # noqa: BLE001 — the ML layer must never break a scan
        return {"available": False,
                "note": f"ML analysis error ({type(exc).__name__})."}


# Alias used by the backend integrations
analyze_url_ml = analyze_url

