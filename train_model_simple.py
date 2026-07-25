"""
train_model_simple.py — Simplified Model Training (No sklearn dependencies)

This script trains a LightGBM model directly without relying on sklearn's
problematic compiled extensions on Windows. It creates a compatible model
file for Zyra's ML link analyzer.

Output:
  - zyra_phishing_model.joblib — Trained model with scaler and feature info
"""

import os
import sys
import time
import json
import random
import struct
from pathlib import Path

import numpy as np

# Try to import LightGBM
try:
    import lightgbm as lgb
    print("✓ LightGBM detected — using gradient boosting model")
    USE_LIGHTGBM = True
except ImportError:
    print("✗ LightGBM not found. Please install: pip install lightgbm")
    sys.exit(1)

# Import our feature extractor
from url_feature_extractor import extract_url_features


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

MODEL_OUTPUT_PATH = "zyra_phishing_model.joblib"
RANDOM_SEED = 42


# ──────────────────────────────────────────────
# Dataset Generation
# ──────────────────────────────────────────────

def generate_phishing_urls():
    """Generate phishing URL examples."""
    phishing_urls = [
        "http://192.168.1.1/login.php",
        "https://bit.ly/3xM7abc",
        "http://paypa1.com/secure/login",
        "https://login-verify.xyz/account/update",
        "http://facbook.com/reset-password",
        "https://secure-login.tk/verify?email=test",
        "http://192.168.0.1/admin/login",
        "https://appleid-verify.ml/secure",
        "http://amazon-account.gq/update/payment",
        "https://netflix-billing.cf/confirm",
        "http://chase-bank.xyz/signin",
        "https://wellsfargo-secure.top/verify",
        "http://bankofamerica.login.cf/update",
        "https://paypal-security.ml/account",
        "http://ebay-payment.gq/confirm",
        "https://dropbox-share.tk/access",
        "http://icloud-verify.xyz/login",
        "https://gmail-security.cf/update",
        "http://outlook-account.top/signin",
        "https://yahoo-mail.ml/verify",
        "http://192.168.1.100/secure/login",
        "https://account-verify.xyz/update/password",
        "http://secure-login.tk/confirm/identity",
        "https://banking-secure.gq/signin",
        "http://credential-reset.cf/verify",
        "https://authenticate.ml/login/secure",
        "http://password-reset.xyz/update",
        "http://recover-account.top/verify",
        "https://security-alert.cf/confirm",
        "http://suspicious-activity.gq/login",
        "https://transaction-verify.tk/secure",
        "http://wallet-update.xyz/payment",
        "https://invoice-payment.ml/confirm",
        "http://refund-status.cf/verify",
        "https://unusual-activity.top/alert",
    ]
    
    # Add variations
    base_phishing = [
        "login", "verify", "secure", "account", "update", "confirm",
        "banking", "password", "credential", "authenticate", "reset",
        "recover", "alert", "security", "payment", "wallet", "transaction"
    ]
    
    suspicious_tlds = [".xyz", ".top", ".gq", ".ml", ".cf", ".tk"]
    
    for keyword in base_phishing[:8]:
        for tld in suspicious_tlds[:3]:
            phishing_urls.append(f"https://{keyword}-secure{tld}/login/verify")
            phishing_urls.append(f"http://{keyword}.{tld[1:]}/account/update")
    
    return phishing_urls


def generate_benign_urls():
    """Generate benign URL examples."""
    benign_urls = [
        "https://www.google.com",
        "https://www.google.com/search?q=test",
        "https://mail.google.com",
        "https://drive.google.com",
        "https://www.youtube.com",
        "https://www.youtube.com/watch?v=test",
        "https://github.com",
        "https://github.com/user/repo",
        "https://stackoverflow.com",
        "https://stackoverflow.com/questions/123",
        "https://www.linkedin.com",
        "https://www.linkedin.com/in/user",
        "https://twitter.com",
        "https://twitter.com/user/status/123",
        "https://www.reddit.com",
        "https://www.reddit.com/r/python",
        "https://www.facebook.com",
        "https://www.instagram.com",
        "https://www.whatsapp.com",
        "https://telegram.org",
        "https://www.amazon.com",
        "https://www.amazon.com/dp/B08N5WRWNW",
        "https://www.ebay.com",
        "https://www.netflix.com",
        "https://www.netflix.com/browse",
        "https://www.spotify.com",
        "https://www.microsoft.com",
        "https://www.apple.com",
        "https://www.adobe.com",
        "https://www.dropbox.com",
        "https://www.wikipedia.org",
        "https://en.wikipedia.org/wiki/Machine_learning",
        "https://www.python.org",
        "https://pypi.org",
        "https://www.docker.com",
        "https://aws.amazon.com",
        "https://cloud.google.com",
        "https://zoom.us",
        "https://www.slack.com",
        "https://www.figma.com",
    ]
    
    # Generate more variations
    for _ in range(80):
        domain = random.choice([
            "example.com", "test.com", "demo.com", "sample.com",
            "blog.com", "news.com", "shop.com", "app.com"
        ])
        path = random.choice([
            "/home", "/about", "/contact", "/products", "/services",
            "/blog/post-1", "/page/about-us", "/item/123"
        ])
        query = random.choice(["", "?id=123", "?page=2", "?search=test"])
        protocol = random.choice(["https://www.", "https://", "http://www."])
        benign_urls.append(f"{protocol}{domain}{path}{query}")
    
    return benign_urls


# ──────────────────────────────────────────────
# Feature Extraction & Training
# ──────────────────────────────────────────────

def prepare_dataset():
    """Prepare training dataset."""
    print("\n📊 Preparing dataset...")
    
    # Generate URLs
    phishing_urls = generate_phishing_urls()
    benign_urls = generate_benign_urls()
    
    all_urls = phishing_urls + benign_urls
    all_labels = [1] * len(phishing_urls) + [0] * len(benign_urls)
    
    # Shuffle
    combined = list(zip(all_urls, all_labels))
    random.seed(RANDOM_SEED)
    random.shuffle(combined)
    all_urls, all_labels = zip(*combined)
    
    n_total = len(all_urls)
    n_phishing = len(phishing_urls)
    n_benign = len(benign_urls)
    
    print(f"  Total URLs: {n_total}")
    print(f"  Phishing: {n_phishing} ({n_phishing/n_total*100:.1f}%)")
    print(f"  Benign: {n_benign} ({n_benign/n_total*100:.1f}%)")
    
    # Extract features
    print("\n🔧 Extracting features...")
    start_time = time.time()
    
    features_list = []
    for idx, url in enumerate(all_urls):
        if idx % 50 == 0:
            print(f"  Processing {idx}/{n_total}...")
        features = extract_url_features(url)
        features_list.append(features)
    
    X = np.array(features_list, dtype=np.float32)
    y = np.array(all_labels, dtype=np.int32)
    
    elapsed = time.time() - start_time
    print(f"  ✓ Feature extraction completed in {elapsed:.2f}s")
    print(f"  ✓ Feature matrix shape: {X.shape}")
    
    return X, y


def train_lightgbm_model(X, y):
    """Train LightGBM model directly."""
    print("\n" + "=" * 60)
    print("  TRAINING LIGHTGBM MODEL")
    print("=" * 60)
    
    # Split data (simple random split without sklearn)
    n_samples = len(X)
    n_train = int(n_samples * 0.7)
    n_val = int(n_samples * 0.15)
    
    # Shuffle indices
    indices = np.arange(n_samples)
    np.random.seed(RANDOM_SEED)
    np.random.shuffle(indices)
    
    train_idx = indices[:n_train]
    val_idx = indices[n_train:n_train+n_val]
    test_idx = indices[n_train+n_val:]
    
    X_train, y_train = X[train_idx], y[train_idx]
    X_val, y_val = X[val_idx], y[val_idx]
    X_test, y_test = X[test_idx], y[test_idx]
    
    print(f"\n📊 Data Split:")
    print(f"  Training: {len(X_train)} samples")
    print(f"  Validation: {len(X_val)} samples")
    print(f"  Test: {len(X_test)} samples")
    
    # Create LightGBM datasets
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    # Train model
    print("\n🚀 Training LightGBM model...")
    start_time = time.time()
    
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'max_depth': 7,
        'learning_rate': 0.05,
        'n_estimators': 100,
        'min_child_samples': 20,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'reg_alpha': 0.1,
        'reg_lambda': 0.1,
        'random_state': RANDOM_SEED,
        'verbose': -1,
    }
    
    model = lgb.train(
        params,
        train_data,
        num_boost_round=100,
        valid_sets=[val_data],
        callbacks=[
            lgb.early_stopping(20),
            lgb.log_evaluation(0)
        ]
    )
    
    training_time = time.time() - start_time
    print(f"  ✓ Training completed in {training_time:.2f}s")
    
    # Evaluate
    print("\n📊 Model Evaluation:")
    
    # Predict on test set
    y_pred_proba = model.predict(X_test)
    y_pred = (y_pred_proba > 0.5).astype(int)
    
    # Calculate metrics manually
    tp = np.sum((y_pred == 1) & (y_test == 1))
    tn = np.sum((y_pred == 0) & (y_test == 0))
    fp = np.sum((y_pred == 1) & (y_test == 0))
    fn = np.sum((y_pred == 0) & (y_test == 1))
    
    accuracy = (tp + tn) / len(y_test)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    metrics = {
        'accuracy': float(accuracy),
        'precision': float(precision),
        'recall': float(recall),
        'f1_score': float(f1),
        'training_time': float(training_time),
        'model_type': 'LightGBM',
        'n_features': X.shape[1],
        'n_samples': int(n_samples),
    }
    
    print(f"  Accuracy:  {accuracy:.4f}")
    print(f"  Precision: {precision:.4f}")
    print(f"  Recall:    {recall:.4f}")
    print(f"  F1-Score:  {f1:.4f}")
    
    print(f"\n🔢 Confusion Matrix:")
    print(f"  True Negatives:  {tn}")
    print(f"  False Positives: {fp}")
    print(f"  False Negatives: {fn}")
    print(f"  True Positives:  {tp}")
    
    # Feature importance
    print("\n🎯 Top 10 Most Important Features:")
    feature_names = [
        "url_length", "hostname_length", "path_length",
        "dot_count", "hyphen_count", "at_count", "question_mark_count",
        "equals_count", "percent_count", "underscore_count",
        "double_slash_count", "has_ip_host", "has_url_shortener",
        "has_suspicious_tld", "digit_ratio_domain", "digit_ratio_url",
        "subdomain_count", "typosquatting_distance", "phishing_keyword_count",
        "path_token_count"
    ]
    
    importance = model.feature_importance(importance_type='gain')
    indices = np.argsort(importance)[::-1][:10]
    
    for i, idx in enumerate(indices, 1):
        print(f"  {i:2d}. {feature_names[idx]:25s}: {importance[idx]:.2f}")
    
    return model, metrics


# ──────────────────────────────────────────────
# Model Saving
# ──────────────────────────────────────────────

def save_model(model, metrics):
    """Save model in a format compatible with ml_link_analyzer."""
    print("\n" + "=" * 60)
    print("  SAVING MODEL")
    print("=" * 60)
    
    # Create a simple scaler (standardization parameters)
    # We'll compute these from a sample of features
    print("\n🔧 Computing scaler parameters...")
    
    # Generate sample data to compute mean/std
    sample_urls = generate_phishing_urls()[:20] + generate_benign_urls()[:20]
    sample_features = np.array([extract_url_features(url) for url in sample_urls])
    
    scaler_mean = np.mean(sample_features, axis=0)
    scaler_std = np.std(sample_features, axis=0)
    scaler_std[scaler_std == 0] = 1  # Avoid division by zero
    
    print(f"  ✓ Scaler computed from {len(sample_urls)} samples")
    
    # Create model package
    model_package = {
        'model': model,
        'scaler': {
            'mean': scaler_mean,
            'std': scaler_std,
            'type': 'standard'
        },
        'metrics': metrics,
        'feature_names': [
            "url_length", "hostname_length", "path_length",
            "dot_count", "hyphen_count", "at_count", "question_mark_count",
            "equals_count", "percent_count", "underscore_count",
            "double_slash_count", "has_ip_host", "has_url_shortener",
            "has_suspicious_tld", "digit_ratio_domain", "digit_ratio_url",
            "subdomain_count", "typosquatting_distance", "phishing_keyword_count",
            "path_token_count"
        ],
        'version': '1.0.0',
        'trained_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    
    # Save to joblib
    joblib.dump(model_package, MODEL_OUTPUT_PATH)
    
    # Get file size
    file_size = os.path.getsize(MODEL_OUTPUT_PATH)
    file_size_mb = file_size / (1024 * 1024)
    
    print(f"\n✓ Model saved to: {MODEL_OUTPUT_PATH}")
    print(f"  File size: {file_size_mb:.2f} MB")
    print(f"  Model type: {metrics['model_type']}")
    print(f"  Features: {metrics['n_features']}")
    print(f"  Training samples: {metrics['n_samples']}")
    print(f"  Accuracy: {metrics['accuracy']:.4f}")
    print(f"  F1-Score: {metrics['f1_score']:.4f}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    """Main training pipeline."""
    print("\n" + "=" * 60)
    print("  ZYRA PHISHING DETECTION MODEL TRAINER (Simple)")
    print("=" * 60)
    
    # Set random seeds
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    
    # Prepare dataset
    X, y = prepare_dataset()
    
    # Train model
    model, metrics = train_lightgbm_model(X, y)
    
    # Save model
    save_model(model, metrics)
    
    print("\n" + "=" * 60)
    print("  TRAINING COMPLETE")
    print("=" * 60)
    print(f"\n✓ Model saved to: {MODEL_OUTPUT_PATH}")
    print("✓ Ready for inference with analyze_link_ml()")
    print()


if __name__ == "__main__":
    main()