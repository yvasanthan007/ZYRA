# Reproducible, leakage-resistant split and evaluation for URL datasets.
from urllib.parse import urlparse
import numpy as np
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import GroupShuffleSplit
from backend.ml_phishing.features import registered_domain

def _registrable_host(host):
    host = (host or "").strip("[]").lower().rstrip(".")
    try:
        import ipaddress
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        import tldextract
        suffix = tldextract.extract(host)
        if suffix.domain and suffix.suffix:
            return f"{suffix.domain}.{suffix.suffix}"
    except Exception:
        pass
    return registered_domain(host) or host

def split_indices(urls, labels, seed=42):
    # Exact duplicate URLs are rejected; registrable host groups cannot cross partitions.
    # The test partition is held out and must not be used to fit or select a model.
    if len(urls) != len(labels) or len(set(labels)) != 2:
        raise ValueError("Split requires equal URL/label counts and both classes.")
    normalized = [str(url).strip().lower() for url in urls]
    if len(normalized) != len(set(normalized)):
        raise ValueError("Duplicate URLs must be resolved before splitting.")
    groups = []
    for url in urls:
        parsed = urlparse(url if "://" in url else "https://" + url)
        groups.append(_registrable_host(parsed.hostname or url) or url.lower())
    first = GroupShuffleSplit(n_splits=1, test_size=0.15, random_state=seed)
    train_val, test = next(first.split(urls, labels, groups))
    remaining_groups = [groups[i] for i in train_val]
    remaining_urls = [urls[i] for i in train_val]
    remaining_labels = [labels[i] for i in train_val]
    second = GroupShuffleSplit(n_splits=1, test_size=(0.15 / 0.85), random_state=seed + 1)
    train_local, val_local = next(second.split(remaining_urls, remaining_labels, remaining_groups))
    train = [train_val[i] for i in train_local]
    validation = [train_val[i] for i in val_local]
    parts = (train, validation, list(test))
    for indices in parts:
        if len({labels[i] for i in indices}) != 2:
            raise ValueError("Grouped split does not contain both classes in every partition.")
    group_sets = [{groups[i] for i in indices} for indices in parts]
    if any(group_sets[i] & group_sets[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError("Registrable-domain leakage detected across splits.")
    return parts

def binary_metrics(labels, probabilities, threshold=0.35):
    actual = np.asarray(labels, dtype=int)
    predicted = (np.asarray(probabilities, dtype=float) >= threshold).astype(int)
    matrix = confusion_matrix(actual, predicted, labels=[0, 1])
    return {
        "decision_threshold": float(threshold),
        "precision": round(float(precision_score(actual, predicted, zero_division=0)), 4),
        "recall": round(float(recall_score(actual, predicted, zero_division=0)), 4),
        "f1": round(float(f1_score(actual, predicted, zero_division=0)), 4),
        "confusion_matrix": {
            "labels": ["legitimate", "phishing"],
            "matrix": matrix.astype(int).tolist(),
            "tn": int(matrix[0, 0]), "fp": int(matrix[0, 1]),
            "fn": int(matrix[1, 0]), "tp": int(matrix[1, 1]),
        },
        "test_size": int(len(actual)),
    }
