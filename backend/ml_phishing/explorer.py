# Dataset explorer for the exact deterministic training corpus and model.
import math
from urllib.parse import urlparse
from backend.ml_phishing.dataset import build_dataset
from backend.ml_phishing.evaluation import split_indices
from backend.ml_phishing.features import FEATURE_NAMES, extract_features, feature_vector, registered_domain
from backend.ml_phishing.predictor import _load
from backend.ml_phishing.evaluation import binary_metrics
from backend.ml_phishing.live_history import list_live_records
DATASET_VERSION = "builtin-seed-v1-seed42-2500-per-class"

def dataset_snapshot():
    urls, labels, stats = build_dataset(per_class=2500, seed=42)
    train, validation, test = split_indices(urls, labels, seed=42)
    split_by_index = {i: "train" for i in train}
    split_by_index.update({i: "validation" for i in validation})
    split_by_index.update({i: "test" for i in test})
    model, _meta = _load()
    predictions = {}
    probabilities = {}
    evaluation = None
    if model is not None:
        x = [feature_vector(urls[i]) for i in test]
        class_index = next((i for i, value in enumerate(model.classes_)
                            if value == 1 or str(value).strip().lower() in ("phishing", "phish", "malicious")), None)
        if class_index is not None:
            proba = model.predict_proba(x)
            probabilities = {index: float(row[class_index]) for index, row in zip(test, proba)}
            predictions = {index: int(model.classes_[int(max(range(len(row)), key=lambda j: row[j]))]) for index, row in zip(test, proba)}
            evaluation = binary_metrics([labels[i] for i in test], [probabilities[i] for i in test])
    records = []
    for i, (url, label) in enumerate(zip(urls, labels)):
        feature_values = extract_features(url)
        item = {"sample_id": f"seed-{i + 1:05d}", "url": url,
                "label": "phishing" if label else "legitimate",
                "label_value": int(label), "split": split_by_index[i],
                "features": feature_values, "prediction": None,
                "risk_score": None, "correct": None}
        if i in predictions:
            item["prediction"] = "phishing" if predictions[i] else "legitimate"
            item["risk_score"] = round(probabilities[i] * 100, 2)
            item["correct"] = predictions[i] == int(label)
        records.append(item)
    missing_feature_values = sum(
        value is None or (isinstance(value, float) and not math.isfinite(value))
        for row in records for value in row["features"].values()
    )
    summary = {
        "source": stats["source"], "dataset_version": stats.get("version", DATASET_VERSION),
        "record_count": len(records), "class_balance": {"legitimate": int(len(labels) - sum(labels)), "phishing": int(sum(labels))},
        "missing_values": {"url": sum(not bool(u) for u in urls), "label": sum(l not in (0, 1) for l in labels), "features": missing_feature_values},
        "duplicate_urls": len(urls) - len({u.strip().lower() for u in urls}),
        "split_counts": {name: sum(r["split"] == name for r in records) for name in ("train", "validation", "test")},
        "feature_names": FEATURE_NAMES,
        "predictions_evaluated": bool(model),
        "evaluation": evaluation,
    }
    return records, summary

def query_dataset(search="", label="all", split="all", page=1, page_size=25):
    records, summary = dataset_snapshot()
    records = records + list_live_records()
    needle = str(search or "").strip().lower()
    if label in ("legitimate", "phishing"):
        records = [row for row in records if row.get("label") == label]
    if split in ("train", "validation", "test", "live"):
        records = [row for row in records if row.get("split") == split]
    if needle:
        records = [row for row in records if needle in row["url"].lower() or needle in row.get("sample_id", row.get("record_id", "")).lower()]
    page_size = max(1, min(int(page_size), 100))
    page = max(1, int(page))
    return {"summary": summary, "total": len(records), "page": page, "page_size": page_size,
            "records": records[(page - 1) * page_size:page * page_size]}
