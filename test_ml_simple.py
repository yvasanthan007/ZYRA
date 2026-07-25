"""
test_ml_simple.py — Simple Test for ML Link Analysis (No dependencies on speak/screen_ocr)

This test directly tests the ML components without importing the full link_analysis module.
"""

import os
import sys
import time

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

# Import only the ML components (no speak/screen_ocr dependencies)
from url_feature_extractor import extract_url_features, extract_url_features_dict
from ml_link_analyzer import load_model_once, analyze_link_ml, is_model_loaded


def print_section(title):
    """Print a formatted test section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_test(name, passed, details=""):
    """Print test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {name}")
    if details:
        print(f"         | {details}")


# ──────────────────────────────────────────────
# Test 1: Feature Extraction
# ──────────────────────────────────────────────

def test_feature_extraction():
    """Test URL feature extraction."""
    print_section("TEST 1: Feature Extraction")
    
    test_cases = [
        {
            'url': 'https://www.google.com',
            'expected_features': {
                'url_length': 22,
                'hostname_length': 14,
                'has_ip_host': 0,
                'has_url_shortener': 0,
                'has_suspicious_tld': 0,
                'typosquatting_distance': 0,
                'phishing_keyword_count': 0,
            }
        },
        {
            'url': 'http://192.168.1.1/login',
            'expected_features': {
                'has_ip_host': 1,
                'phishing_keyword_count': 1,
            }
        },
        {
            'url': 'https://bit.ly/3xM7abc',
            'expected_features': {
                'has_url_shortener': 1,
                'url_length': 21,
            }
        },
        {
            'url': 'https://login-verify.xyz/account/update',
            'expected_features': {
                'has_suspicious_tld': 1,
                'phishing_keyword_count': 3,
            }
        },
    ]
    
    all_passed = True
    
    for test_case in test_cases:
        url = test_case['url']
        expected = test_case['expected_features']
        
        # Test numpy array output
        features = extract_url_features(url)
        passed = isinstance(features, np.ndarray)
        passed = passed and len(features) == 20
        passed = passed and features.dtype == np.float32
        
        if not passed:
            print_test(f"Feature extraction: {url}", False, "Invalid output format")
            all_passed = False
            continue
        
        # Test dictionary output
        features_dict = extract_url_features_dict(url)
        
        # Check expected features
        for feature_name, expected_value in expected.items():
            actual_value = features_dict.get(feature_name)
            if actual_value != expected_value:
                print_test(f"{feature_name} for {url}", False, 
                          f"Expected: {expected_value}, Got: {actual_value}")
                all_passed = False
            else:
                print_test(f"{feature_name} for {url}", True)
    
    return all_passed


# ──────────────────────────────────────────────
# Test 2: Model Loading
# ──────────────────────────────────────────────

def test_model_loading():
    """Test ML model loading."""
    print_section("TEST 2: Model Loading")
    
    # Check if model file exists
    model_path = "zyra_phishing_model.joblib"
    model_exists = os.path.exists(model_path)
    
    print_test("Model file exists", model_exists, f"Path: {model_path}")
    
    if not model_exists:
        print("\n⚠️  Model not found. Run 'python train_model_numpy.py' first.")
        return False
    
    # Try to load model
    loaded = load_model_once(model_path)
    print_test("Model loads successfully", loaded)
    
    if loaded:
        print_test("Model is marked as loaded", is_model_loaded())
        print(f"  Model type: {_get_model_type()}")
    
    return loaded


def _get_model_type():
    """Get model type from loaded model."""
    try:
        import joblib
        model_package = joblib.load("zyra_phishing_model.joblib")
        return model_package.get('metrics', {}).get('model_type', 'Unknown')
    except:
        return 'Unknown'


# ──────────────────────────────────────────────
# Test 3: ML Inference
# ──────────────────────────────────────────────

def test_ml_inference():
    """Test ML inference."""
    print_section("TEST 3: ML Inference")
    
    if not is_model_loaded():
        print("⚠️  Skipping ML inference tests (model not loaded)")
        return False
    
    test_cases = [
        ('https://www.google.com', 'safe', '< 0.35'),
        ('http://192.168.1.1/login', 'dangerous', '>= 0.70'),
        ('https://bit.ly/3xM7abc', 'suspicious', '0.35-0.70'),
        ('https://login-verify.xyz/account/update', 'dangerous', '>= 0.70'),
        ('https://www.gooogle.com', 'suspicious', '0.35-0.70'),
    ]
    
    all_passed = True
    
    for url, expected_verdict, prob_range in test_cases:
        result = analyze_link_ml(url, use_virustotal=False)
        
        if not result or not result.get('ml_available'):
            print_test(f"ML inference: {url[:50]}", False, "ML not available")
            all_passed = False
            continue
        
        verdict = result['verdict']
        probability = result['probability']
        
        # Check verdict
        verdict_match = verdict == expected_verdict
        details = f"Expected: {expected_verdict}, Got: {verdict}, Prob: {probability:.2%}"
        print_test(f"Verdict: {url[:50]}", verdict_match, details)
        
        if not verdict_match:
            all_passed = False
        
        # Check probability range
        if prob_range == '< 0.35':
            prob_match = probability < 0.35
        elif prob_range == '>= 0.70':
            prob_match = probability >= 0.70
        else:  # 0.35-0.70
            prob_match = 0.35 <= probability < 0.70
        
        print_test(f"Probability range: {url[:50]}", prob_match, 
                  f"Prob: {probability:.2%}, Range: {prob_range}")
        
        if not prob_match:
            all_passed = False
        
        # Check execution time
        exec_time = result.get('execution_time_ms', 0)
        fast_enough = exec_time < 30
        print_test(f"Performance (<30ms): {url[:50]}", fast_enough,
                  f"Time: {exec_time:.2f}ms")
        
        if not fast_enough:
            all_passed = False
    
    return all_passed


# ──────────────────────────────────────────────
# Test 4: Voice Text Generation
# ──────────────────────────────────────────────

def test_voice_text():
    """Test voice-friendly text generation."""
    print_section("TEST 4: Voice Text Generation")
    
    test_cases = [
        ('https://www.google.com', 'safe', 'safe'),
        ('http://192.168.1.1/login', 'dangerous', 'dangerous'),
        ('https://bit.ly/3xM7abc', 'suspicious', 'suspicious'),
    ]
    
    all_passed = True
    
    for url, expected_verdict, _ in test_cases:
        result = analyze_link_ml(url, use_virustotal=False)
        
        if not result or not result.get('ml_available'):
            print_test(f"Voice text: {url[:50]}", False, "ML not available")
            all_passed = False
            continue
        
        voice_text = result.get('voice_text', '')
        has_voice_text = len(voice_text) > 0
        has_verdict_word = expected_verdict in voice_text.lower() or 'safe' in voice_text.lower()
        
        passed = has_voice_text and has_verdict_word
        details = f"Voice text length: {len(voice_text)}"
        print_test(f"Voice text: {url[:50]}", passed, details)
        
        if passed:
            print(f"         | \"{voice_text[:100]}...\"")
        
        if not passed:
            all_passed = False
    
    return all_passed


# ──────────────────────────────────────────────
# Test 5: Performance Benchmark
# ──────────────────────────────────────────────

def test_performance():
    """Test performance benchmark."""
    print_section("TEST 5: Performance Benchmark")
    
    if not is_model_loaded():
        print("⚠️  Skipping performance tests (model not loaded)")
        return False
    
    print("\nRunning 100-iteration benchmark...")
    
    test_urls = [
        "https://www.google.com",
        "https://www.facebook.com",
        "http://192.168.1.1/login",
        "https://bit.ly/3xM7abc",
        "https://login-verify.xyz/account/update",
    ]
    
    times = []
    for _ in range(100):
        url = np.random.choice(test_urls)
        start = time.time()
        analyze_link_ml(url, use_virustotal=False)
        elapsed = time.time() - start
        times.append(elapsed * 1000)
    
    print(f"\nResults:")
    print(f"  Mean:   {np.mean(times):.2f}ms")
    print(f"  Median: {np.median(times):.2f}ms")
    print(f"  Min:    {np.min(times):.2f}ms")
    print(f"  Max:    {np.max(times):.2f}ms")
    print(f"  Std:    {np.std(times):.2f}ms")
    print(f"  Under 30ms: {sum(1 for t in times if t < 30) / 100 * 100:.1f}%")
    
    passed = np.mean(times) < 30
    print_test("Performance target (<30ms mean)", passed, 
              f"Mean: {np.mean(times):.2f}ms")
    
    return passed


# ──────────────────────────────────────────────
# Main Test Runner
# ──────────────────────────────────────────────

def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("  ZYRA ML LINK ANALYSIS — TEST SUITE (Simple)")
    print("=" * 70)
    
    results = {}
    
    # Test 1: Feature extraction
    results['feature_extraction'] = test_feature_extraction()
    
    # Test 2: Model loading
    results['model_loading'] = test_model_loading()
    
    # Test 3: ML inference (only if model loaded)
    if results['model_loading']:
        results['ml_inference'] = test_ml_inference()
    else:
        print("\n⚠️  Skipping ML inference tests (model not loaded)")
        results['ml_inference'] = False
    
    # Test 4: Voice text (only if model loaded)
    if results['model_loading']:
        results['voice_text'] = test_voice_text()
    else:
        print("\n⚠️  Skipping voice text tests (model not loaded)")
        results['voice_text'] = False
    
    # Test 5: Performance (only if model loaded)
    if results['model_loading']:
        results['performance'] = test_performance()
    else:
        print("\n⚠️  Skipping performance tests (model not loaded)")
        results['performance'] = False
    
    # Print summary
    print_section("TEST SUMMARY")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, test_passed in results.items():
        status = "✅" if test_passed else "❌"
        print(f"{status} {test_name.replace('_', ' ').title()}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
    
    print("=" * 70)
    
    return passed == total


if __name__ == "__main__":
    try:
        success = run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Test suite failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)