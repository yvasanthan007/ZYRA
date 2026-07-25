"""
ml_link_analyzer.py — Zyra ML-Powered Link Analysis Module

Provides real-time phishing detection using a pre-trained LightGBM/RandomForest model.
Combines ML probability with optional VirusTotal API fallback for enhanced accuracy.

Performance target: <30ms per URL analysis (offline feature extraction + inference)

Usage:
  from ml_link_analyzer import analyze_link_ml, load_model_once
  
  # Load model once at startup
  load_model_once()
  
  # Analyze URLs
  result = analyze_link_ml("https://example.com")
  print(result['verdict'])  # 'safe', 'suspicious', or 'dangerous'
  print(result['probability'])  # 0.00 to 1.00
"""

import os
import time
import json
import hashlib
from typing import Dict, Optional, Tuple

import numpy as np
import joblib

# Import our feature extractor
from url_feature_extractor import extract_url_features

# Import VirusTotal checker from existing link_analysis
try:
    from link_analysis import check_url_virustotal, VIRUSTOTAL_API_KEY
except ImportError:
    check_url_virustotal = None
    VIRUSTOTAL_API_KEY = None


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

MODEL_PATH = "zyra_phishing_model.joblib"

# Probability thresholds for verdict classification
THRESHOLD_SAFE = 0.35
THRESHOLD_SUSPICIOUS = 0.70

# Cache for VirusTotal results (avoid repeated API calls)
_vt_cache = {}
_vt_cache_duration = 3600  # 1 hour


# ──────────────────────────────────────────────
# Model Loading (Singleton Pattern)
# ──────────────────────────────────────────────

_model_package = None
_model_loaded = False


def load_model_once(model_path: str = MODEL_PATH) -> bool:
    """
    Load the ML model once at system startup.
    This function should be called during Zyra initialization.
    
    Args:
        model_path: Path to the .joblib model file
    
    Returns:
        bool: True if model loaded successfully, False otherwise
    """
    global _model_package, _model_loaded
    
    if _model_loaded:
        return True
    
    if not os.path.exists(model_path):
        print(f"⚠ ML model not found at {model_path}")
        print("  Run 'python train_model.py' to train the model first.")
        print("  Falling back to heuristic analysis.")
        return False
    
    try:
        start_time = time.time()
        _model_package = joblib.load(model_path)
        load_time = time.time() - start_time
        
        # Validate model package
        required_keys = ['model', 'scaler', 'feature_names']
        for key in required_keys:
            if key not in _model_package:
                raise ValueError(f"Model package missing required key: {key}")
        
        _model_loaded = True
        
        print(f"✓ ML model loaded successfully ({load_time*1000:.1f}ms)")
        print(f"  Model type: {_model_package.get('metrics', {}).get('model_type', 'Unknown')}")
        print(f"  Features: {len(_model_package['feature_names'])}")
        
        return True
        
    except Exception as e:
        print(f"✗ Failed to load ML model: {e}")
        print("  Falling back to heuristic analysis.")
        _model_package = None
        _model_loaded = False
        return False


def is_model_loaded() -> bool:
    """Check if ML model is currently loaded."""
    return _model_loaded and _model_package is not None


# ──────────────────────────────────────────────
# ML Inference
# ──────────────────────────────────────────────

def predict_phishing_probability(url: str) -> Optional[float]:
    """
    Predict phishing probability for a URL using the ML model.
    
    Args:
        url: URL string to analyze
    
    Returns:
        float: Probability of phishing (0.0 to 1.0), or None if model not loaded
    """
    if not is_model_loaded():
        return None
    
    try:
        # Extract features
        features = extract_url_features(url)
        
        # Reshape for single sample
        features = features.reshape(1, -1)
        
        # Scale features
        scaler = _model_package['scaler']
        if isinstance(scaler, dict) and scaler.get('type') == 'standard':
            # NumPy neural network scaler
            scaler_mean = scaler['mean']
            scaler_std = scaler['std']
            features_scaled = (features - scaler_mean) / scaler_std
        else:
            # Sklearn scaler
            features_scaled = scaler.transform(features)
        
        # Predict probability
        model = _model_package['model']
        
        # Check model type
        if isinstance(model, dict) and model.get('type') == 'simple_nn':
            # NumPy neural network
            W1, b1 = model['W1'], model['b1']
            W2, b2 = model['W2'], model['b2']
            W3, b3 = model['W3'], model['b3']
            
            # Forward pass
            z1 = np.dot(features_scaled, W1) + b1
            a1 = np.maximum(0, z1)  # ReLU
            z2 = np.dot(a1, W2) + b2
            a2 = np.maximum(0, z2)  # ReLU
            z3 = np.dot(a2, W3) + b3
            probability = 1 / (1 + np.exp(-z3))  # Sigmoid
            probability = float(probability[0][0])
        else:
            # Sklearn/LightGBM model
            probability = model.predict_proba(features_scaled)[0][1]  # Probability of class 1 (phishing)
        
        return float(probability)
    
    except Exception as e:
        print(f"⚠ ML prediction error: {e}")
        return None


# ──────────────────────────────────────────────
# VirusTotal Integration
# ──────────────────────────────────────────────

def _get_vt_cache_key(url: str) -> str:
    """Generate cache key for VirusTotal results."""
    return hashlib.md5(url.encode()).hexdigest()


def check_virustotal_cached(url: str) -> Optional[Tuple[str, str]]:
    """
    Check VirusTotal with caching to avoid repeated API calls.
    
    Args:
        url: URL to check
    
    Returns:
        tuple: (verdict, details) or None if not available
    """
    if not VIRUSTOTAL_API_KEY or check_url_virustotal is None:
        return None
    
    # Check cache
    cache_key = _get_vt_cache_key(url)
    if cache_key in _vt_cache:
        cached_result, cached_time = _vt_cache[cache_key]
        if time.time() - cached_time < _vt_cache_duration:
            return cached_result
    
    # Make API call
    try:
        result = check_url_virustotal(url)
        if result and result[0] != "error":
            _vt_cache[cache_key] = (result, time.time())
        return result
    except Exception as e:
        print(f"⚠ VirusTotal check failed: {e}")
        return None


# ──────────────────────────────────────────────
# Main Analysis Function
# ──────────────────────────────────────────────

def analyze_link_ml(url: str, use_virustotal: bool = True) -> Dict:
    """
    Analyze a URL using ML model with optional VirusTotal fallback.
    
    Args:
        url: URL string to analyze
        use_virustotal: If True, check VirusTotal when ML is uncertain
    
    Returns:
        dict: Analysis result with keys:
            - url: Original URL
            - verdict: 'safe', 'suspicious', or 'dangerous'
            - probability: ML phishing probability (0.0 to 1.0)
            - confidence: 'high', 'medium', or 'low'
            - ml_available: Whether ML model was used
            - vt_verdict: VirusTotal verdict (if checked)
            - reasons: List of human-readable reasons
            - voice_text: Voice-friendly summary string
            - execution_time_ms: Analysis time in milliseconds
    """
    start_time = time.time()
    
    # Initialize result
    result = {
        'url': url,
        'verdict': 'safe',
        'probability': 0.0,
        'confidence': 'low',
        'ml_available': False,
        'vt_verdict': None,
        'reasons': [],
        'voice_text': '',
        'execution_time_ms': 0.0,
    }
    
    # Get ML prediction
    ml_probability = predict_phishing_probability(url)
    
    if ml_probability is not None:
        result['ml_available'] = True
        result['probability'] = round(ml_probability, 4)
        
        # Determine verdict based on probability
        if ml_probability >= THRESHOLD_SUSPICIOUS:
            result['verdict'] = 'dangerous'
            result['confidence'] = 'high'
            result['reasons'].append(
                f"ML model predicts high phishing probability ({ml_probability*100:.1f}%)"
            )
        elif ml_probability >= THRESHOLD_SAFE:
            result['verdict'] = 'suspicious'
            result['confidence'] = 'medium'
            result['reasons'].append(
                f"ML model predicts moderate phishing probability ({ml_probability*100:.1f}%)"
            )
        else:
            result['verdict'] = 'safe'
            result['confidence'] = 'high'
            result['reasons'].append(
                f"ML model predicts low phishing probability ({ml_probability*100:.1f}%)"
            )
    
    # VirusTotal fallback for uncertain cases
    vt_verdict = None
    if use_virustotal and result['verdict'] in ['suspicious', 'safe']:
        vt_result = check_virustotal_cached(url)
        
        if vt_result:
            vt_verdict, vt_details = vt_result
            result['vt_verdict'] = vt_verdict
            
            if vt_verdict == 'malicious':
                result['verdict'] = 'dangerous'
                result['confidence'] = 'high'
                result['reasons'].append(f"VirusTotal: {vt_details}")
            elif vt_verdict == 'suspicious' and result['verdict'] == 'safe':
                result['verdict'] = 'suspicious'
                result['confidence'] = 'medium'
                result['reasons'].append(f"VirusTotal: {vt_details}")
    
    # Generate voice-friendly text
    result['voice_text'] = _generate_voice_text(result)
    
    # Calculate execution time
    execution_time = time.time() - start_time
    result['execution_time_ms'] = round(execution_time * 1000, 2)
    
    return result


def _generate_voice_text(result: Dict) -> str:
    """
    Generate voice-friendly text summary for the analysis result.
    
    Args:
        result: Analysis result dictionary
    
    Returns:
        str: Voice-friendly summary
    """
    verdict = result['verdict']
    probability = result['probability']
    ml_available = result['ml_available']
    vt_verdict = result.get('vt_verdict')
    
    if verdict == 'dangerous':
        if vt_verdict == 'malicious':
            return (
                "Warning! This link has been flagged as malicious by security scanners. "
                "Do not visit this website."
            )
        elif ml_available:
            return (
                f"Warning! This link appears to be dangerous. "
                f"The security model detected a {probability*100:.0f}% probability of phishing. "
                "I recommend avoiding this website."
            )
        else:
            return "Warning! This link appears to be dangerous. Please avoid visiting it."
    
    elif verdict == 'suspicious':
        if vt_verdict == 'suspicious':
            return (
                "Caution. This link appears suspicious according to security scanners. "
                "Proceed with caution if you choose to visit."
            )
        elif ml_available:
            return (
                f"Caution. This link appears somewhat suspicious. "
                f"The security model detected a {probability*100:.0f}% probability of phishing. "
                "Please verify the website before entering any sensitive information."
            )
        else:
            return "Caution. This link appears suspicious. Please verify before proceeding."
    
    else:  # safe
        if ml_available:
            return (
                f"I have analyzed the link. It appears to be safe. "
                f"The security model detected only a {probability*100:.0f}% probability of phishing."
            )
        else:
            return "I have analyzed the link. It appears to be safe."


def analyze_link_ml_json(url: str, use_virustotal: bool = True) -> str:
    """
    Analyze URL and return JSON string (for API/backend integration).
    
    Args:
        url: URL string to analyze
        use_virustotal: If True, check VirusTotal when ML is uncertain
    
    Returns:
        str: JSON string of analysis result
    """
    result = analyze_link_ml(url, use_virustotal)
    return json.dumps(result, indent=2)


# ──────────────────────────────────────────────
# Batch Analysis
# ──────────────────────────────────────────────

def analyze_batch(urls: list, use_virustotal: bool = False) -> list:
    """
    Analyze multiple URLs in batch.
    
    Args:
        urls: List of URL strings
        use_virustotal: If True, check VirusTotal (slower)
    
    Returns:
        list: List of analysis result dictionaries
    """
    results = []
    
    for url in urls:
        result = analyze_link_ml(url, use_virustotal=use_virustotal)
        results.append(result)
    
    return results


# ──────────────────────────────────────────────
# Performance Testing
# ──────────────────────────────────────────────

def benchmark_performance(n_iterations: int = 100) -> Dict:
    """
    Benchmark ML inference performance.
    
    Args:
        n_iterations: Number of test iterations
    
    Returns:
        dict: Performance metrics
    """
    if not is_model_loaded():
        return {'error': 'Model not loaded'}
    
    test_urls = [
        "https://www.google.com",
        "https://www.facebook.com",
        "http://192.168.1.1/login",
        "https://bit.ly/3xM7abc",
        "https://login-verify.xyz/account/update",
        "https://www.gooogle.com",
        "https://www.paypa1.com/login",
        "https://example.com/path/to/page",
    ]
    
    times = []
    
    for _ in range(n_iterations):
        url = np.random.choice(test_urls)
        start = time.time()
        analyze_link_ml(url, use_virustotal=False)
        elapsed = time.time() - start
        times.append(elapsed * 1000)  # Convert to ms
    
    return {
        'iterations': n_iterations,
        'mean_ms': np.mean(times),
        'median_ms': np.median(times),
        'min_ms': np.min(times),
        'max_ms': np.max(times),
        'std_ms': np.std(times),
        'under_30ms_pct': sum(1 for t in times if t < 30) / n_iterations * 100,
    }


# ──────────────────────────────────────────────
# Standalone Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("  ZYRA ML LINK ANALYZER — Standalone Test")
    print("=" * 70)
    print()
    
    # Try to load model
    print("📦 Loading ML model...")
    if load_model_once():
        print("  ✓ Model loaded successfully\n")
    else:
        print("  ⚠ Model not available — predictions will be None\n")
    
    # Test URLs
    test_urls = [
        ("https://www.google.com", "Legitimate - Google"),
        ("https://www.facebook.com", "Legitimate - Facebook"),
        ("https://www.github.com", "Legitimate - GitHub"),
        ("http://192.168.1.1/login", "Suspicious - IP address"),
        ("https://bit.ly/3xM7abc", "Suspicious - URL shortener"),
        ("https://login-verify.xyz/account/update", "Phishing - keywords + TLD"),
        ("https://www.gooogle.com", "Typosquatting - Google"),
        ("https://www.paypa1.com/login", "Typosquatting - PayPal"),
        ("https://secure-login.tk/verify?email=test", "Phishing - multiple indicators"),
        ("https://example.com/path/to/page", "Legitimate - example.com"),
    ]
    
    print("🔍 Testing URL analysis:")
    print("-" * 70)
    
    for url, description in test_urls:
        print(f"\n{description}")
        print(f"URL: {url}")
        
        result = analyze_link_ml(url, use_virustotal=False)
        
        verdict_icon = {"safe": "✅", "suspicious": "⚠️", "dangerous": "🚫"}.get(result['verdict'], "❓")
        
        print(f"Verdict: {verdict_icon} {result['verdict'].upper()}")
        print(f"Probability: {result['probability']*100:.2f}%")
        print(f"Confidence: {result['confidence']}")
        print(f"ML Available: {result['ml_available']}")
        print(f"Execution Time: {result['execution_time_ms']:.2f}ms")
        
        if result['reasons']:
            print("Reasons:")
            for reason in result['reasons']:
                print(f"  • {reason}")
        
        print(f"Voice: {result['voice_text']}")
    
    print("\n" + "=" * 70)
    
    # Performance benchmark
    if is_model_loaded():
        print("\n⚡ Performance Benchmark (100 iterations)...")
        print("-" * 70)
        
        perf = benchmark_performance(100)
        
        if 'error' not in perf:
            print(f"  Mean:   {perf['mean_ms']:.2f}ms")
            print(f"  Median: {perf['median_ms']:.2f}ms")
            print(f"  Min:    {perf['min_ms']:.2f}ms")
            print(f"  Max:    {perf['max_ms']:.2f}ms")
            print(f"  Std:    {perf['std_ms']:.2f}ms")
            print(f"  Under 30ms: {perf['under_30ms_pct']:.1f}%")
            
            if perf['mean_ms'] < 30:
                print("\n  ✓ Performance target met (<30ms average)")
            else:
                print("\n  ⚠ Performance target not met (>=30ms average)")
        
        print("=" * 70)