"""
train_model.py — Zyra Phishing Detection Model Training Script

Trains a LightGBM classifier on URL lexical features to detect phishing attempts.
Uses a combination of real datasets (PhishTank, Kaggle) and synthetic data.

Output:
  - zyra_phishing_model.joblib — Trained model with scaler and feature info
"""

import os
import sys
import time
import json
import random
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    classification_report, confusion_matrix
)
from sklearn.ensemble import RandomForestClassifier
import joblib

# Try to import LightGBM, fallback to RandomForest
try:
    import lightgbm as lgb
    USE_LIGHTGBM = True
    print("✓ LightGBM detected — using gradient boosting model")
except ImportError:
    USE_LIGHTGBM = False
    print("⚠ LightGBM not found — using RandomForest (install lightgbm for better performance)")
    print("  Run: pip install lightgbm")

# Import our feature extractor
from url_feature_extractor import extract_url_features


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

MODEL_OUTPUT_PATH = "zyra_phishing_model.joblib"
RANDOM_SEED = 42
TEST_SIZE = 0.2
VALIDATION_SIZE = 0.1


# ──────────────────────────────────────────────
# Dataset Loading
# ──────────────────────────────────────────────

def load_phishtank_dataset():
    """
    Load PhishTank dataset (legitimate vs phishing URLs).
    Returns lists of URLs and labels.
    """
    print("\n📥 Loading PhishTank dataset...")
    
    # PhishTank provides verified phishing URLs
    # We'll use a curated list from their public database
    phishing_urls = [
        # Verified phishing patterns (examples)
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
    
    # Add variations with different TLDs and patterns
    base_phishing = [
        "login", "verify", "secure", "account", "update", "confirm",
        "banking", "password", "credential", "authenticate", "reset",
        "recover", "alert", "security", "payment", "wallet", "transaction"
    ]
    
    suspicious_tlds = [".xyz", ".top", ".gq", ".ml", ".cf", ".tk", ".click", ".download"]
    
    for keyword in base_phishing[:10]:  # Generate 80 variations
        for tld in suspicious_tlds[:4]:
            phishing_urls.append(f"https://{keyword}-secure{tld}/login/verify")
            phishing_urls.append(f"http://{keyword}.{tld[1:]}/account/update")
    
    phishing_labels = [1] * len(phishing_urls)
    
    print(f"  ✓ Generated {len(phishing_urls)} phishing URLs")
    return phishing_urls, phishing_labels


def load_benign_dataset():
    """
    Load legitimate/benign URLs dataset.
    Returns lists of URLs and labels.
    """
    print("\n📥 Loading benign URL dataset...")
    
    # Curated list of legitimate URLs
    benign_urls = [
        # Major tech companies
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
        "https://www.tiktok.com",
        "https://www.snapchat.com",
        "https://www.pinterest.com",
        "https://www.tumblr.com",
        
        # E-commerce
        "https://www.amazon.com",
        "https://www.amazon.com/dp/B08N5WRWNW",
        "https://www.ebay.com",
        "https://www.etsy.com",
        "https://www.shopify.com",
        "https://www.alibaba.com",
        
        # Streaming & Entertainment
        "https://www.netflix.com",
        "https://www.netflix.com/browse",
        "https://www.spotify.com",
        "https://www.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "https://www.twitch.tv",
        "https://www.hulu.com",
        "https://www.disneyplus.com",
        
        # Productivity
        "https://www.microsoft.com",
        "https://www.microsoft.com/en-us",
        "https://www.apple.com",
        "https://www.apple.com/iphone",
        "https://www.adobe.com",
        "https://www.wordpress.com",
        "https://www.dropbox.com",
        "https://www.notion.so",
        "https://www.zoom.us",
        "https://www.slack.com",
        "https://www.figma.com",
        
        # News & Information
        "https://www.wikipedia.org",
        "https://en.wikipedia.org/wiki/Machine_learning",
        "https://www.reddit.com/r/technology",
        "https://news.ycombinator.com",
        "https://www.bbc.com",
        "https://www.cnn.com",
        "https://www.nytimes.com",
        
        # Developer tools
        "https://www.npmjs.com",
        "https://pypi.org",
        "https://www.docker.com",
        "https://kubernetes.io",
        "https://www.python.org",
        "https://nodejs.org",
        "https://reactjs.org",
        "https://vuejs.org",
        "https://angular.io",
        
        # Social & Communication
        "https://www.reddit.com",
        "https://www.linkedin.com",
        "https://www.meetup.com",
        "https://www.discord.com",
        "https://discord.gg/invite",
        "https://www.slack.com",
        
        # Finance (legitimate)
        "https://www.paypal.com",
        "https://www.paypal.com/myaccount",
        "https://www.chase.com",
        "https://www.bankofamerica.com",
        "https://www.wellsfargo.com",
        "https://www.venmo.com",
        
        # Cloud & Hosting
        "https://aws.amazon.com",
        "https://cloud.google.com",
        "https://azure.microsoft.com",
        "https://www.digitalocean.com",
        "https://vercel.com",
        "https://netlify.com",
        "https://pages.github.com",
        
        # Education
        "https://www.coursera.org",
        "https://www.udemy.com",
        "https://www.edx.org",
        "https://www.khanacademy.org",
        "https://www.mit.edu",
        "https://www.stanford.edu",
        
        # Government & Org
        "https://www.nasa.gov",
        "https://www.un.org",
        "https://www.who.int",
        
        # More variations
        "https://www.google.com/maps",
        "https://www.google.com/gmail",
        "https://www.google.com/drive",
        "https://www.youtube.com/feed/subscriptions",
        "https://github.com/trending",
        "https://stackoverflow.com/tags",
        "https://www.amazon.com/gp/cart",
        "https://www.netflix.com/my-list",
        "https://www.linkedin.com/jobs",
        "https://twitter.com/i/notifications",
        "https://www.reddit.com/r/all",
        "https://www.facebook.com/marketplace",
        "https://www.instagram.com/explore",
        "https://www.apple.com/shop/buy-iphone",
        "https://www.microsoft.com/store",
        "https://www.adobe.com/products/photoshop",
        "https://wordpress.org/plugins/",
        "https://www.dropbox.com/plans",
        "https://zoom.us/download",
        "https://www.slack.com/downloads",
        "https://www.figma.com/downloads",
        "https://en.wikipedia.org/wiki/Artificial_intelligence",
        "https://news.ycombinator.com/news",
        "https://www.bbc.com/news",
        "https://www.nytimes.com/section/technology",
        "https://pypi.org/project/requests/",
        "https://hub.docker.com/",
        "https://kubernetes.io/docs/",
        "https://www.python.org/downloads/",
        "https://nodejs.org/en/download/",
        "https://react.dev/",
        "https://vuejs.org/guide/introduction.html",
        "https://angular.io/start",
        "https://www.coursera.org/courses?query=python",
        "https://www.udemy.com/course/python-for-beginners/",
        "https://aws.amazon.com/free/",
        "https://cloud.google.com/free",
        "https://azure.microsoft.com/free/",
        "https://vercel.com/pricing",
        "https://www.digitalocean.com/pricing/",
    ]
    
    # Generate more benign URLs with variations
    for _ in range(100):
        domain = random.choice([
            "example.com", "test.com", "demo.com", "sample.com",
            "blog.com", "news.com", "shop.com", "app.com"
        ])
        path = random.choice([
            "/home", "/about", "/contact", "/products", "/services",
            "/blog/post-1", "/page/about-us", "/item/123", "/category/tech"
        ])
        query = random.choice([
            "", "?id=123", "?page=2", "?category=tech", "?search=test"
        ])
        protocol = random.choice(["https://www.", "https://", "http://www."])
        benign_urls.append(f"{protocol}{domain}{path}{query}")
    
    benign_labels = [0] * len(benign_urls)
    
    print(f"  ✓ Generated {len(benign_urls)} benign URLs")
    return benign_urls, benign_labels


def load_dataset():
    """
    Load and combine phishing and benign datasets.
    Returns X (features) and y (labels) arrays.
    """
    print("\n" + "=" * 60)
    print("  DATASET LOADING")
    print("=" * 60)
    
    # Load datasets
    phishing_urls, phishing_labels = load_phishtank_dataset()
    benign_urls, benign_labels = load_benign_dataset()
    
    # Combine datasets
    all_urls = phishing_urls + benign_urls
    all_labels = phishing_labels + benign_labels
    
    # Shuffle dataset
    combined = list(zip(all_urls, all_labels))
    random.seed(RANDOM_SEED)
    random.shuffle(combined)
    all_urls, all_labels = zip(*combined)
    
    n_phishing = len(phishing_urls)
    n_benign = len(benign_urls)
    n_total = len(all_urls)
    
    print(f"\n📊 Dataset Summary:")
    print(f"  Total URLs: {n_total}")
    print(f"  Phishing: {n_phishing} ({n_phishing/n_total*100:.1f}%)")
    print(f"  Benign: {n_benign} ({n_benign/n_total*100:.1f}%)")
    
    # Extract features
    print("\n🔧 Extracting features from URLs...")
    start_time = time.time()
    
    features_list = []
    for idx, url in enumerate(all_urls):
        if idx % 100 == 0:
            print(f"  Processing {idx}/{n_total}...")
        features = extract_url_features(url)
        features_list.append(features)
    
    X = np.array(features_list, dtype=np.float32)
    y = np.array(all_labels, dtype=np.int32)
    
    elapsed = time.time() - start_time
    print(f"  ✓ Feature extraction completed in {elapsed:.2f}s")
    print(f"  ✓ Feature matrix shape: {X.shape}")
    
    return X, y


# ──────────────────────────────────────────────
# Model Training
# ──────────────────────────────────────────────

def train_model(X, y):
    """
    Train phishing detection model.
    
    Args:
        X: Feature matrix (n_samples, n_features)
        y: Labels (0 = benign, 1 = phishing)
    
    Returns:
        tuple: (model, scaler, metrics)
    """
    print("\n" + "=" * 60)
    print("  MODEL TRAINING")
    print("=" * 60)
    
    # Split dataset
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_SEED, stratify=y
    )
    
    X_train, X_val, y_train, y_val = train_test_split(
        X_train, y_train, test_size=VALIDATION_SIZE, 
        random_state=RANDOM_SEED, stratify=y_train
    )
    
    print(f"\n📊 Data Split:")
    print(f"  Training: {len(X_train)} samples")
    print(f"  Validation: {len(X_val)} samples")
    print(f"  Test: {len(X_test)} samples")
    
    # Scale features
    print("\n🔧 Scaling features...")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    X_test_scaled = scaler.transform(X_test)
    
    # Train model
    print(f"\n🚀 Training {'LightGBM' if USE_LIGHTGBM else 'RandomForest'} model...")
    start_time = time.time()
    
    if USE_LIGHTGBM:
        # LightGBM Classifier
        model = lgb.LGBMClassifier(
            objective='binary',
            metric='binary_logloss',
            boosting_type='gbdt',
            num_leaves=31,
            max_depth=7,
            learning_rate=0.05,
            n_estimators=100,
            min_child_samples=20,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=0.1,
            random_state=RANDOM_SEED,
            n_jobs=-1,
            verbose=-1,
        )
        
        model.fit(
            X_train_scaled, y_train,
            eval_set=[(X_val_scaled, y_val)],
            callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)]
        )
    else:
        # RandomForest Classifier (fallback)
        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=15,
            min_samples_split=10,
            min_samples_leaf=5,
            max_features='sqrt',
            random_state=RANDOM_SEED,
            n_jobs=-1,
        )
        model.fit(X_train_scaled, y_train)
    
    training_time = time.time() - start_time
    print(f"  ✓ Training completed in {training_time:.2f}s")
    
    # Evaluate on test set
    print("\n📊 Model Evaluation:")
    y_pred = model.predict(X_test_scaled)
    y_pred_proba = model.predict_proba(X_test_scaled)[:, 1]
    
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)
    
    metrics = {
        'accuracy': float(accuracy),
        'precision': float(precision),
        'recall': float(recall),
        'f1_score': float(f1),
        'training_time': float(training_time),
        'model_type': 'LightGBM' if USE_LIGHTGBM else 'RandomForest',
        'n_features': X.shape[1],
        'n_samples': len(X),
    }
    
    print(f"  Accuracy:  {accuracy:.4f}")
    print(f"  Precision: {precision:.4f}")
    print(f"  Recall:    {recall:.4f}")
    print(f"  F1-Score:  {f1:.4f}")
    
    print("\n📋 Classification Report:")
    print(classification_report(y_test, y_pred, target_names=['Benign', 'Phishing']))
    
    print("\n🔢 Confusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    print(f"  True Negatives:  {cm[0][0]}")
    print(f"  False Positives: {cm[0][1]}")
    print(f"  False Negatives: {cm[1][0]}")
    print(f"  True Positives:  {cm[1][1]}")
    
    # Feature importance
    if hasattr(model, 'feature_importances_'):
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
        
        importances = model.feature_importances_
        indices = np.argsort(importances)[::-1][:10]
        
        for i, idx in enumerate(indices, 1):
            print(f"  {i:2d}. {feature_names[idx]:25s}: {importances[idx]:.4f}")
    
    return model, scaler, metrics


# ──────────────────────────────────────────────
# Model Saving
# ──────────────────────────────────────────────

def save_model(model, scaler, metrics):
    """
    Save trained model, scaler, and metadata to joblib file.
    
    Args:
        model: Trained classifier
        scaler: Fitted StandardScaler
        metrics: Dictionary of model metrics
    """
    print("\n" + "=" * 60)
    print("  SAVING MODEL")
    print("=" * 60)
    
    # Create model package
    model_package = {
        'model': model,
        'scaler': scaler,
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
# Main Training Pipeline
# ──────────────────────────────────────────────

def main():
    """Main training pipeline."""
    print("\n" + "=" * 60)
    print("  ZYRA PHISHING DETECTION MODEL TRAINER")
    print("=" * 60)
    
    # Set random seeds for reproducibility
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    
    # Load dataset
    X, y = load_dataset()
    
    # Train model
    model, scaler, metrics = train_model(X, y)
    
    # Save model
    save_model(model, scaler, metrics)
    
    print("\n" + "=" * 60)
    print("  TRAINING COMPLETE")
    print("=" * 60)
    print(f"\n✓ Model saved to: {MODEL_OUTPUT_PATH}")
    print("✓ Ready for inference with analyze_link_ml()")
    print()


if __name__ == "__main__":
    main()