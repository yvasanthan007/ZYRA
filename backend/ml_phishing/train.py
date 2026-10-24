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
from backend.ml_phishing.evaluation import binary_metrics, split_indices
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
    "Train the required XGBoost model and report validation plus held-out test metrics."
    if len(urls) != len(labels) or len(set(labels)) != 2:
        raise ValueError("Training requires equal URL/label counts and both classes (0 and 1).")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("Labels must use 1=phishing and 0=legitimate.")
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    X = [feature_vector(u) for u in urls]
    y = list(labels)
    train_idx, validation_idx, test_idx = split_indices(urls, y, seed)
    X_train = [X[i] for i in train_idx]
    y_train = [y[i] for i in train_idx]
    X_validation = [X[i] for i in validation_idx]
    y_validation = [y[i] for i in validation_idx]
    X_test = [X[i] for i in test_idx]
    y_test = [y[i] for i in test_idx]

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

    # ── XGBoost candidate ──
    # XGBoost is mandatory for the configured production inference engine.
    try:
        from xgboost import XGBClassifier
        candidates["XGBClassifier"] = XGBClassifier(
            n_estimators=n_estimators, max_depth=4, learning_rate=0.08,
            subsample=0.85, colsample_bytree=0.85, min_child_weight=2,
            reg_lambda=2.0, eval_metric="logloss", n_jobs=-1,
            random_state=seed, tree_method="hist",
        )
    except Exception as exc:
        raise RuntimeError("XGBoost is required to train the production phishing model.") from exc

    results, fitted = {}, {}
    for name, model in candidates.items():
        if name == "XGBClassifier":
            model.fit(X_train, y_train, eval_set=[(X_validation, y_validation)], verbose=False)
        else:
            model.fit(X_train, y_train)
        val_probabilities = model.predict_proba(X_validation)
        phishing_index = next((i for i, label in enumerate(model.classes_)
                               if label == 1 or str(label).strip().lower() in ("phishing", "phish", "malicious")), None)
        if phishing_index is None:
            raise ValueError(f"{name} does not expose a phishing class")
        results[name] = _metrics(y_validation, val_probabilities[:, phishing_index])
        fitted[name] = model
        if verbose:
            print(f"  {name} validation: {results[name]}")

    # Select using validation only; the independent grouped test set remains unseen.
    if "XGBClassifier" not in fitted:
        raise RuntimeError("XGBoost is required for ZYRA URL phishing inference.")
    best_name = "XGBClassifier"
    final_model = fitted[best_name]
    test_probabilities = final_model.predict_proba(X_test)
    phishing_index = next(i for i, label in enumerate(final_model.classes_)
                          if label == 1 or str(label).strip().lower() in ("phishing", "phish", "malicious"))
    test_metrics = binary_metrics(y_test, test_probabilities[:, phishing_index], threshold=0.35)
    results[best_name] = {**results[best_name], "held_out_test": test_metrics}
    if verbose:
        print(f"  selected using validation: {best_name}")
        print(f"  held-out test: {test_metrics}")

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
        "evaluation": {"selected_model": best_name,
                       "dataset_version": dataset_stats.get("version", "unspecified"),
                       "split_strategy": "registrable-domain grouped train/validation/test 70/15/15",
                       "test_set_size": results[best_name].get("held_out_test", {}).get("test_size"),
                       "test_metrics": results[best_name].get("held_out_test")},
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
        description="Train ZYRA's XGBoost phishing classifier.")
    parser.add_argument("--csv", default=None,
                        help="CSV dataset with url,label columns "
                             "(phishing label = 1). Default: builtin seed dataset.")
    parser.add_argument("--per-class", type=int, default=2500,
                        help="Seed-dataset size per class (default 2500).")
    parser.add_argument("--n-estimators", type=int, default=300,
                        help="Number of XGBoost boosting rounds (default 300).")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed for split, models and seed dataset.")
    args = parser.parse_args(argv)

    print("ZYRA XGBoost phishing classifier — training")
    urls, labels, stats = build_dataset(csv_path=args.csv,
                                        per_class=args.per_class,
                                        seed=args.seed)
    stats["version"] = stats.get("version", f"builtin-seed-v1-seed{args.seed}-{args.per_class}-per-class")
    print(f"  dataset: {stats['source']} — {stats['size']} URLs "
          f"({stats['phishing']} phishing / {stats['legitimate']} legitimate)")
    print("  validation metrics (model selection) and independent grouped test metrics:")

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

