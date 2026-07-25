"""
train_model_numpy.py — Train Phishing Detection Model using Pure NumPy

This script trains a simple neural network using ONLY NumPy (no sklearn, pandas, or lightgbm).
This bypasses Windows Application Control policy restrictions while still providing
ML-based phishing detection.

Architecture:
  - Input: 20 URL features
  - Hidden Layer 1: 32 neurons (ReLU)
  - Hidden Layer 2: 16 neurons (ReLU)
  - Output: 1 neuron (Sigmoid)

Output:
  - zyra_phishing_model.joblib — Trained model with weights and scaler
"""

import os
import sys
import time
import json
import random
import struct

import numpy as np
import joblib

# Import our feature extractor
from url_feature_extractor import extract_url_features


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

MODEL_OUTPUT_PATH = "zyra_phishing_model.joblib"
RANDOM_SEED = 42
LEARNING_RATE = 0.01
EPOCHS = 500
BATCH_SIZE = 16


# ──────────────────────────────────────────────
# Neural Network Implementation (Pure NumPy)
# ──────────────────────────────────────────────

class SimpleNeuralNetwork:
    """Simple feedforward neural network using only NumPy."""
    
    def __init__(self, input_size=20, hidden1=32, hidden2=16, output_size=1):
        """Initialize network with random weights."""
        np.random.seed(RANDOM_SEED)
        
        # Xavier initialization
        self.W1 = np.random.randn(input_size, hidden1) * np.sqrt(2.0 / input_size)
        self.b1 = np.zeros((1, hidden1))
        
        self.W2 = np.random.randn(hidden1, hidden2) * np.sqrt(2.0 / hidden1)
        self.b2 = np.zeros((1, hidden2))
        
        self.W3 = np.random.randn(hidden2, output_size) * np.sqrt(2.0 / hidden2)
        self.b3 = np.zeros((1, output_size))
    
    def relu(self, x):
        """ReLU activation function."""
        return np.maximum(0, x)
    
    def relu_derivative(self, x):
        """Derivative of ReLU."""
        return (x > 0).astype(float)
    
    def sigmoid(self, x):
        """Sigmoid activation function."""
        # Clip to prevent overflow
        x = np.clip(x, -500, 500)
        return 1 / (1 + np.exp(-x))
    
    def forward(self, X):
        """Forward pass through the network."""
        # Layer 1
        self.z1 = np.dot(X, self.W1) + self.b1
        self.a1 = self.relu(self.z1)
        
        # Layer 2
        self.z2 = np.dot(self.a1, self.W2) + self.b2
        self.a2 = self.relu(self.z2)
        
        # Output layer
        self.z3 = np.dot(self.a2, self.W3) + self.b3
        self.output = self.sigmoid(self.z3)
        
        return self.output
    
    def backward(self, X, y, output, learning_rate):
        """Backward pass (backpropagation)."""
        m = X.shape[0]
        
        # Output layer gradients
        dz3 = output - y.reshape(-1, 1)
        dW3 = np.dot(self.a2.T, dz3) / m
        db3 = np.sum(dz3, axis=0, keepdims=True) / m
        
        # Hidden layer 2 gradients
        da2 = np.dot(dz3, self.W3.T)
        dz2 = da2 * self.relu_derivative(self.z2)
        dW2 = np.dot(self.a1.T, dz2) / m
        db2 = np.sum(dz2, axis=0, keepdims=True) / m
        
        # Hidden layer 1 gradients
        da1 = np.dot(dz2, self.W2.T)
        dz1 = da1 * self.relu_derivative(self.z1)
        dW1 = np.dot(X.T, dz1) / m
        db1 = np.sum(dz1, axis=0, keepdims=True) / m
        
        # Update weights
        self.W3 -= learning_rate * dW3
        self.b3 -= learning_rate * db3
        self.W2 -= learning_rate * dW2
        self.b2 -= learning_rate * db2
        self.W1 -= learning_rate * dW1
        self.b1 -= learning_rate * db1
    
    def train(self, X, y, epochs, learning_rate, batch_size, X_val, y_val):
        """Train the network using mini-batch gradient descent."""
        best_val_loss = float('inf')
        patience = 20
        patience_counter = 0
        
        for epoch in range(epochs):
            # Shuffle training data
            indices = np.arange(X.shape[0])
            np.random.shuffle(indices)
            X_shuffled = X[indices]
            y_shuffled = y[indices]
            
            # Mini-batch training
            for i in range(0, X.shape[0], batch_size):
                X_batch = X_shuffled[i:i+batch_size]
                y_batch = y_shuffled[i:i+batch_size]
                
                # Forward pass
                output = self.forward(X_batch)
                
                # Backward pass
                self.backward(X_batch, y_batch, output, learning_rate)
            
            # Calculate training loss
            train_output = self.forward(X)
            train_loss = -np.mean(y * np.log(train_output + 1e-8) + 
                                 (1 - y) * np.log(1 - train_output + 1e-8))
            
            # Calculate validation loss
            val_output = self.forward(X_val)
            val_loss = -np.mean(y_val * np.log(val_output + 1e-8) + 
                               (1 - y_val) * np.log(1 - val_output + 1e-8))
            
            # Print progress
            if (epoch + 1) % 50 == 0:
                print(f"  Epoch {epoch+1}/{epochs} - Train Loss: {train_loss:.4f}, Val Loss: {val_loss:.4f}")
            
            # Early stopping
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    print(f"  Early stopping at epoch {epoch+1}")
                    break
    
    def predict_proba(self, X):
        """Predict probability of class 1 (phishing)."""
        output = self.forward(X)
        return output.flatten()
    
    def predict(self, X, threshold=0.5):
        """Predict class labels."""
        proba = self.predict_proba(X)
        return (proba > threshold).astype(int)


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
# Training Pipeline
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
    y = np.array(all_labels, dtype=np.float32)
    
    elapsed = time.time() - start_time
    print(f"  ✓ Feature extraction completed in {elapsed:.2f}s")
    print(f"  ✓ Feature matrix shape: {X.shape}")
    
    return X, y


def train_model(X, y):
    """Train the neural network."""
    print("\n" + "=" * 60)
    print("  TRAINING NEURAL NETWORK")
    print("=" * 60)
    
    # Split data
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
    
    # Normalize features (simple standardization)
    print("\n🔧 Normalizing features...")
    scaler_mean = np.mean(X_train, axis=0)
    scaler_std = np.std(X_train, axis=0)
    scaler_std[scaler_std == 0] = 1  # Avoid division by zero
    
    X_train_norm = (X_train - scaler_mean) / scaler_std
    X_val_norm = (X_val - scaler_mean) / scaler_std
    X_test_norm = (X_test - scaler_mean) / scaler_std
    
    # Create and train model
    print("\n🚀 Training neural network...")
    start_time = time.time()
    
    model = SimpleNeuralNetwork(input_size=20, hidden1=32, hidden2=16, output_size=1)
    model.train(X_train_norm, y_train, EPOCHS, LEARNING_RATE, BATCH_SIZE, 
                X_val_norm, y_val)
    
    training_time = time.time() - start_time
    print(f"  ✓ Training completed in {training_time:.2f}s")
    
    # Evaluate
    print("\n📊 Model Evaluation:")
    
    y_pred_proba = model.predict_proba(X_test_norm)
    y_pred = model.predict(X_test_norm, threshold=0.5)
    
    # Calculate metrics
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
        'model_type': 'NumPy Neural Network',
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
    
    return model, scaler_mean, scaler_std, metrics


# ──────────────────────────────────────────────
# Model Saving
# ──────────────────────────────────────────────

def save_model(model, scaler_mean, scaler_std, metrics):
    """Save model in a format compatible with ml_link_analyzer."""
    print("\n" + "=" * 60)
    print("  SAVING MODEL")
    print("=" * 60)
    
    # Create model package
    model_package = {
        'model': {
            'W1': model.W1,
            'b1': model.b1,
            'W2': model.W2,
            'b2': model.b2,
            'W3': model.W3,
            'b3': model.b3,
            'type': 'simple_nn'
        },
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
    print("  ZYRA PHISHING DETECTION MODEL TRAINER (NumPy)")
    print("=" * 60)
    print("  Using pure NumPy neural network (no sklearn/lightgbm)")
    
    # Set random seeds
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    
    # Prepare dataset
    X, y = prepare_dataset()
    
    # Train model
    model, scaler_mean, scaler_std, metrics = train_model(X, y)
    
    # Save model
    save_model(model, scaler_mean, scaler_std, metrics)
    
    print("\n" + "=" * 60)
    print("  TRAINING COMPLETE")
    print("=" * 60)
    print(f"\n✓ Model saved to: {MODEL_OUTPUT_PATH}")
    print("✓ Ready for inference with analyze_link_ml()")
    print()


if __name__ == "__main__":
    main()