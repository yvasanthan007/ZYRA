"""
backend/ml_phishing/predictor.py — Inference for ZYRA's ML phishing
classifier.

Loads the trained model lazily (thread-safe) and exposes analyze_url_ml():
a dict with the phishing probability, a verdict, and the most influential
features for this URL (flagged features ranked by model importance).

Semantics: `probability` is the model's estimated PHISHING probability
(0..1 — higher = MORE dangerous). This is the inverse of ZYRA's safety
score (0..100, higher = safer) reported by backend/url_analyzer/risk_scorer.py;
never display the two side by side without their own labels.

Degradation contract (matches ZYRA's backend style — never raises):
  - scikit-learn / joblib missing or model file missing → {"available": False}
  - ZYRA_ML_DISABLE=1                                   → disabled at runtime
  - ZYRA_ML_MODEL=/path/model.joblib                    → custom model path
"""

import json
import math
import os
import threading
import time
from urllib.parse import urlparse

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
    if override:
        return os.path.abspath(override)
    try:
        import zyra_paths
        bundled = zyra_paths.resource_path("backend", "ml_phishing", "models", "phishing_model.joblib")
        if getattr(__import__("sys"), "frozen", False) and os.path.isfile(bundled):
            return bundled
    except Exception:
        pass
    return _DEFAULT_MODEL_PATH


def _enabled():
    return os.environ.get("ZYRA_ML_DISABLE", "0").strip().lower() not in (
        "1", "true", "yes")


def _load():
    """Lazy, thread-safe model load keyed on path + mtime."""
    path = _model_path()
    try:
        stat = os.stat(path) if os.path.exists(path) else None
        stamp = (stat.st_mtime_ns, stat.st_size) if stat else None
        meta_path = os.path.join(os.path.dirname(path), "model_meta.json")
        meta_stat = os.stat(meta_path) if os.path.exists(meta_path) else None
        meta_stamp = (meta_stat.st_mtime_ns, meta_stat.st_size) if meta_stat else None
    except OSError:
        stamp = meta_stamp = None
    key = (path, stamp, meta_stamp)
    with _LOCK:
        if _CACHE["key"] == key:
            return _CACHE["model"], _CACHE["meta"]
        model = meta = None
        if joblib is not None and os.path.exists(path):
            try:
                payload = joblib.load(path)
                model = payload.get("model") if isinstance(payload, dict) else payload
                stored_features = (payload.get("feature_names")
                                   if isinstance(payload, dict) else None)
                meta_path = os.path.join(os.path.dirname(path), "model_meta.json")
                if os.path.exists(meta_path):
                    with open(meta_path, "r", encoding="utf-8") as fh:
                        meta = json.load(fh)
                declared_features = stored_features or (meta or {}).get("feature_names")
                if not declared_features or list(declared_features) != FEATURE_NAMES:
                    raise ValueError("model feature schema is missing or does not match the inference pipeline")
                if isinstance(payload, dict) and payload.get("algorithm") != "XGBClassifier":
                    raise ValueError("configured production model is not XGBoost")
                if type(model).__name__ != "XGBClassifier":
                    raise ValueError("configured production artifact is not an XGBClassifier")
                expected_count = getattr(model, "n_features_in_", len(FEATURE_NAMES))
                if int(expected_count) != len(FEATURE_NAMES):
                    raise ValueError("model feature count does not match the inference pipeline")
            except Exception as exc:
                print(f"[ML] model unavailable ({type(exc).__name__})")
                model = meta = None
        _CACHE.update({"key": key, "model": model, "meta": meta})
        return model, meta


def _phishing_class_index(model):
    # Resolve phishing class by its label, never by assumed probability order.
    classes = list(getattr(model, "classes_", []))
    hits = [i for i, label in enumerate(classes)
            if label == 1 or str(label).strip().lower() in ("phishing", "phish", "malicious")]
    return hits[0] if len(hits) == 1 else None

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
        "evaluation": (meta or {}).get("evaluation"),
        "n_features": len(FEATURE_NAMES),
        "feature_names": FEATURE_NAMES,
        "probabilities_calibrated": False,
        "sklearn_version": (meta or {}).get("sklearn_version"),
    }

# Probability → verdict mapping (must match risk_scorer.py's ML floor tiers)
_VERDICT_TIERS = [
    (0.90, "PHISHING"),
    (0.75, "LIKELY_PHISHING"),
    (0.55, "SUSPICIOUS"),
    (0.35, "UNSURE"),
]


def _is_ip(host):
    try:
        import ipaddress
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False

def _verdict(prob, decision_threshold=0.35):
    if abs(prob - decision_threshold) < 0.05:
        return "UNCERTAIN"
    if prob >= 0.90:
        return "PHISHING"
    if prob >= 0.75:
        return "LIKELY_PHISHING"
    if prob >= 0.55 or prob >= decision_threshold:
        return "SUSPICIOUS"
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
    # Return the actual XGBoost phishing class probability and explanation.
    started = time.perf_counter()
    try:
        raw = str(url or "").strip()
        if not raw:
            return {"available": False, "note": "Empty URL."}
        parsed = urlparse(raw if "://" in raw else "https://" + raw)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname:
            return {"available": False, "note": "Invalid URL: provide an HTTP(S) URL with a hostname."}
        if not _enabled():
            return {"available": False,
                    "note": "ML classifier disabled via ZYRA_ML_DISABLE."}
        model, meta = _load()
        if model is None:
            return model_info()
        feats = extract_features(raw)
        vec = [float(feats[name]) for name in FEATURE_NAMES]
        phishing_index = _phishing_class_index(model)
        if phishing_index is None:
            return {"available": False,
                    "note": "ML model does not expose an unambiguous phishing class."}
        probabilities = model.predict_proba([vec])[0]
        if len(probabilities) != len(getattr(model, "classes_", [])):
            return {"available": False, "note": "Model output class mapping is inconsistent."}
        prob = float(probabilities[phishing_index])
        if not math.isfinite(prob):
            return {"available": False, "note": "ML model returned a non-finite probability."}
        prob = min(max(prob, 0.0), 1.0)
        threshold = float((meta or {}).get("decision_threshold", 0.35))
        raw_prediction = model.classes_[int(max(range(len(probabilities)), key=lambda i: probabilities[i]))]
        predicted_label = ("phishing" if str(raw_prediction).strip().lower() in
                           ("1", "phishing", "phish", "malicious") else "legitimate")
        # This assessment is part of the actual model feature pipeline, so any
        # deterministic suspicion adjustment is represented by those features,
        # not a second hidden scoring/rule layer.
        explanation = {"available": False, "method": None, "note": "Per-URL contribution explanation unavailable."}
        try:
            import numpy as np
            from xgboost import DMatrix
            contributions = model.get_booster().predict(
                DMatrix(np.asarray([vec], dtype=float), feature_names=FEATURE_NAMES),
                pred_contribs=True,
            )[0]
            base = float(contributions[-1])
            ranked = sorted(zip(FEATURE_NAMES, contributions[:-1]), key=lambda pair: abs(float(pair[1])), reverse=True)
            explanation = {
                "available": True, "method": "XGBoost native TreeSHAP (margin/log-odds)",
                "base_value": round(base, 6),
                "contributions": [{"feature": name, "value": feats[name],
                                    "contribution": round(float(value), 6),
                                    "direction": "increases phishing score" if value > 0 else "decreases phishing score" if value < 0 else "no contribution",
                                    "description": FEATURE_DESCRIPTIONS.get(name, name)}
                                   for name, value in ranked if abs(float(value)) > 1e-8][:10],
                "disclaimer": "Contributions describe this model's output, not proof that a URL is malicious.",
            }
        except Exception as exc:
            explanation["note"] = f"Per-URL contribution explanation unavailable ({type(exc).__name__})."
        importances = _feature_importances(model, meta)
        return {
            "available": True, "url": raw,
            "algorithm": (meta or {}).get("algorithm", type(model).__name__),
            "model_version": (meta or {}).get("version"),
            "probability": round(prob, 6), "phishing_probability": round(prob, 6),
            "percent": round(prob * 100, 2), "risk_score": round(prob * 100, 2),
            "probabilities_calibrated": False,
            "decision_threshold": threshold,
            "verdict": _verdict(prob, threshold), "prediction": predicted_label,
            "risk_band": _risk_band(prob),
            "confidence": round(max(prob, 1.0 - prob), 6),
            "features": feats, "feature_names": FEATURE_NAMES,
            "explanation": explanation,
            "global_feature_importance": [{"feature": name, "importance": round(float(value), 6),
                                           "description": FEATURE_DESCRIPTIONS.get(name, name)}
                                          for name, value in importances],
            "top_signals": explanation.get("contributions", []),
            "analysis_time_ms": round((time.perf_counter() - started) * 1000, 2),
            "metrics": (meta or {}).get("metrics"),
        }
    except Exception as exc:  # noqa: BLE001 — the ML layer must never break a scan
        return {"available": False,
                "note": f"ML analysis error ({type(exc).__name__})."}


# Alias used by the backend integrations
analyze_url_ml = analyze_url

