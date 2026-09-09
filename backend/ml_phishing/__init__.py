"""
backend/ml_phishing/__init__.py — ZYRA ML phishing classifier package.

Machine-learning layer on top of ZYRA's rule-based URL security engine:

    features   — offline lexical feature extraction (28 features)
    dataset    — deterministic seed dataset + external CSV loader
    train      — trainer (python -m backend.ml_phishing.train)
    predictor  — thread-safe inference (analyze_url_ml / model_info)

The ML verdict is advisory signal #19 in the URL pipeline: it contributes a
transparent finding and can raise/force the risk classification, but it can
never make a flagged URL look safer.
"""

from backend.ml_phishing.predictor import (  # noqa: F401
    analyze_url,
    analyze_url_ml,
    model_info,
)
from backend.ml_phishing.features import (  # noqa: F401
    FEATURE_NAMES,
    extract_features,
    feature_vector,
)

__all__ = [
    "analyze_url",
    "analyze_url_ml",
    "model_info",
    "FEATURE_NAMES",
    "extract_features",
    "feature_vector",
]
