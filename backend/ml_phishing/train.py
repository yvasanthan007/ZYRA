"""
backend/ml_phishing/train.py — Train / retrain ZYRA's ML phishing classifier.

Usage (from the repository root):
    python -m backend.ml_phishing.train                     # seed dataset
    python -m backend.ml_phishing.train --csv dataset.csv   # real dataset
    python -m backend.ml_phishing.train --n-estimators 500  # bigger forest

Trains up to three candidates — XGBoost (when installed), RandomForest and
LogisticRegression — on a stratified 80/20 split, keeps the candidate with the
better F1 on the hold-out, and saves the winning model plus metadata:

    backend/ml_phishing/models/phishing_model.joblib
    backend/ml_phishing/models/model_meta.json

XGBoost is preferred on an F1 tie; it is optional so training always works with
scikit-learn alone.
"""

import argparse
import json
import os
import sys
from datetime import datetime

import joblib
import sklearn

from backend.ml_phishing.dataset import build_dataset
from backend.ml_phishing.features import FEATURE_NAMES, feature_vector

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "phishing_model.joblib")
META_PATH = os.path.join(MODEL_DIR, "model_meta.json")
MODEL_VERSION = "1.0.0"


def _metrics(y_true, proba):
    from sklearn.metrics import (accuracy_score, f1_score, precision_score,
                                 recall_score, roc_auc_score)
    # Use a recall-oriented deployment threshold: missed phishing has higher
    # consequence than an additional suspicious warning. Keep threshold recorded.
    threshold = 0.35
    pred = (proba >= threshold).astype(int)
    try:
        from sklearn.metrics import average_precision_score, brier_score_loss
        pr_auc = float(average_precision_score(y_true, proba))
        brier = float(brier_score_loss(y_true, proba))
    except Exception:
        pr_auc = brier = float("nan")
    return {
        "decision_threshold": threshold,
        "accuracy": round(float(accuracy_score(y_true, pred)), 4),
        "precision": round(float(precision_score(y_true, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, proba)), 4),
        "pr_auc": round(pr_auc, 4),
        "brier_score": round(brier, 4),
        "test_size": int(len(y_true)),
    }


def train_models(urls, labels, n_estimators=300, seed=42, verbose=True):
    """
    Train both candidates and return (best_name, best_model, results, holdout).
    holdout is (X_test, y_test) for optional extra evaluation. Built-in
    synthetic-data results are development checks, not estimates of real-world accuracy.
    """
    if len(urls) != len(labels) or len(set(labels)) != 2:
        raise ValueError("Training requires equal URL/label counts and both classes (0 and 1).")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("Labels must use 1=phishing and 0=legitimate.")
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupShuffleSplit, train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    X = [feature_vector(u) for u in urls]
    y = list(labels)
    # Group by registrable host where possible, so URL variants from a single
    # domain cannot appear in both train and hold-out splits.
    from urllib.parse import urlparse
    from backend.ml_phishing.features import registered_domain
    groups = []
    for url in urls:
        parsed = urlparse(url if "://" in url else "https://" + url)
        groups.append(registered_domain(parsed.hostname or url))
    try:
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
        train_idx, test_idx = next(splitter.split(X, y, groups))
        if len(set(y[i] for i in train_idx)) < 2 or len(set(y[i] for i in test_idx)) < 2:
            raise ValueError("group split missing a class")
        X_train, X_test = [X[i] for i in train_idx], [X[i] for i in test_idx]
        y_train, y_test = [y[i] for i in train_idx], [y[i] for i in test_idx]
    except ValueError:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, stratify=y, random_state=seed)

    candidates = {
        "RandomForestClassifier": RandomForestClassifier(
            n_estimators=n_estimators, n_jobs=-1, random_state=seed,
            class_weight="balanced_subsample",
        ),
        "LogisticRegression": Pipeline([
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, C=1.0,
                                       class_weight="balanced",
                                       random_state=seed)),
        ]),
    }

    # ── XGBoost candidate (preferred when installed) ──
    # Gradient-boosted trees are the requested production classifier; the
    # sklearn candidates remain as a guaranteed fallback so training never
    # depends on the optional dependency.
    try:
        from xgboost import XGBClassifier
        candidates["XGBClassifier"] = XGBClassifier(
            n_estimators=n_estimators, max_depth=4, learning_rate=0.08,
            subsample=0.85, colsample_bytree=0.85, min_child_weight=2,
            reg_lambda=2.0, eval_metric="logloss", n_jobs=-1,
            random_state=seed, tree_method="hist",
        )
    except Exception as exc:  # noqa: BLE001 — optional dependency
        if verbose:
            print(f"  (xgboost unavailable: {type(exc).__name__} — "
                  "training sklearn candidates only)")

    results, fitted = {}, {}
    for name, model in candidates.items():
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_test)[:, 1]
        results[name] = _metrics(y_test, proba)
        fitted[name] = model
        if verbose:
            print(f"  {name}: {results[name]}")

    # Prefer XGBoost for production when it meets a reasonable recall floor;
    # otherwise deploy the best F1 model rather than silently missing phish.
    if "XGBClassifier" in fitted and results["XGBClassifier"]["recall"] >= 0.98:
        best_name = "XGBClassifier"
    else:
        best_name = max(results, key=lambda n: (results[n]["f1"], n == "XGBClassifier"))
    if verbose:
        print(f"  selected by policy: {best_name}")

    return best_name, fitted[best_name], results, (X_test, y_test)


def _feature_importance_pairs(best_name, best_model):
    """[(feature, importance)] ranked desc, or None when unavailable."""
    importances = None
    if hasattr(best_model, "feature_importances_"):
        importances = best_model.feature_importances_
    elif hasattr(best_model, "named_steps"):
        clf = best_model.named_steps.get("clf")
        if clf is not None and hasattr(clf, "coef_"):
            importances = abs(clf.coef_[0])
    if importances is None:
        return None
    return sorted(zip(FEATURE_NAMES, (float(i) for i in importances)),
                  key=lambda p: -p[1])


def save_model(best_name, best_model, results, dataset_stats):
    """Persist the winning model (joblib) + metadata (json). Returns meta."""
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(
        {
            "model": best_model,
            "feature_names": FEATURE_NAMES,
            "algorithm": best_name,
            "version": MODEL_VERSION,
            "decision_threshold": 0.35,
        },
        MODEL_PATH,
    )
    meta = {
        "version": MODEL_VERSION,
        "algorithm": best_name,
        "decision_threshold": 0.35,
        "feature_names": FEATURE_NAMES,
        "feature_importances": _feature_importance_pairs(best_name, best_model),
        "metrics": results,
        "dataset": dataset_stats,
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sklearn_version": sklearn.__version__,
        "python": sys.version.split()[0],
    }
    with open(META_PATH, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Train ZYRA's ML phishing classifier.")
    parser.add_argument("--csv", default=None,
                        help="CSV dataset with url,label columns "
                             "(phishing label = 1). Default: builtin seed dataset.")
    parser.add_argument("--per-class", type=int, default=1200,
                        help="Seed-dataset size per class (default 1200).")
    parser.add_argument("--n-estimators", type=int, default=300,
                        help="Tree count for the tree ensembles (default 300).")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed for split, models and seed dataset.")
    args = parser.parse_args(argv)

    print("ZYRA ML phishing classifier — training")
    urls, labels, stats = build_dataset(csv_path=args.csv,
                                        per_class=args.per_class,
                                        seed=args.seed)
    print(f"  dataset: {stats['source']} — {stats['size']} URLs "
          f"({stats['phishing']} phishing / {stats['legitimate']} legitimate)")
    print("  hold-out metrics (stratified 80/20):")

    best_name, best_model, results, _holdout = train_models(
        urls, labels, n_estimators=args.n_estimators, seed=args.seed)
    meta = save_model(best_name, best_model, results, stats)

    print(f"  selected model: {best_name}")
    print(f"  saved model:    {MODEL_PATH}")
    print(f"  saved metadata: {META_PATH}")
    if meta.get("feature_importances"):
        print("  top features:")
        for name, importance in meta["feature_importances"][:8]:
            print(f"    {importance:6.3f}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

