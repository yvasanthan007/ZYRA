# Small append-only store for URL analyses and their explicitly live split.
import json
import os
import threading
from datetime import datetime, timezone
import zyra_paths
_LOCK = threading.Lock()

def _history_path():
    return zyra_paths.writable_path("backend", "ml_phishing", "live_analysis.jsonl")

def add_live_record(url, result):
    record = {"record_id": f"live-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
              "analyzed_at": datetime.now(timezone.utc).isoformat(), "split": "live",
              "url": url, "result": result}
    try:
        with _LOCK, open(_history_path(), "a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return record

def list_live_records():
    # Return recorded live analyses, separate from labeled corpus partitions.
    path = _history_path()
    try:
        with _LOCK, open(path, "r", encoding="utf-8") as stream:
            rows = [json.loads(line) for line in stream if line.strip()]
    except (OSError, ValueError):
        return []
    records = []
    for row in rows:
        result = row.get("result") or {}
        records.append({"sample_id": row.get("record_id"), "url": row.get("url", ""),
                        "label": "unlabeled", "label_value": None, "split": "live",
                        "features": result.get("features", {}),
                        "prediction": result.get("prediction"),
                        "risk_score": result.get("risk_score"), "correct": None,
                        "analyzed_at": row.get("analyzed_at")})
    return records
