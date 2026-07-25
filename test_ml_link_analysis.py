"""
test_ml_link_analysis.py — Comprehensive Test Suite for Zyra ML Link Analysis

Tests:
  1. Feature extraction accuracy
  2. Model training and evaluation
  3. ML inference performance
  4. End-to-end integration
  5. Backward compatibility with heuristics
"""

import os
import sys
import time
import json
import traceback

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

# Import modules to test
from url_feature_extractor import extract_url_features, extract_url_features_dict
from link_analysis import (
    analyze_link_ml_enhanced, initialize_ml_model, 
    is_valid_url, analyze_url_heuristic
)
from ml_link_analyzer import load_model_once, analyze_link_ml, benchmark_performance


# ──────────────────────────────────────────────
# Test Utilities
# ──────────────────────────────────────────────

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


def assert_equal(actual, expected, test_name):
    """Assert two values are equal."""
    passed = actual == expected
    details = f"Expected: {expected}, Got: {actual}"
    print_test(test_name, passed, details)
    return passed


def assert_true(condition, test_name, details=""):
    """Assert condition is True."""
    passed = bool(condition)
    print_test(test_name, passed, details)
    return passed


def assert_false(condition, test_name, details=""):
    """Assert condition is False."""
    passed = not bool(condition)
    print_test(test_name, passed, details)
    return passed


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
                'phishing_keyword_count': 1,  # 'login'
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
                'phishing_keyword_count': 3,  # login, verify, account, update
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
# Test 2: Heuristic Analysis (Fallback)
# ──────────────────────────────────────────────

def test_heuristic_analysis():
    """Test heuristic URL analysis."""
    print_section("TEST 2: Heuristic Analysis (Fallback)")
    
    test_cases = [
        ('https://www.google.com', 'safe'),
        ('http://192.168.1.1/login', 'dangerous'),
        ('https://bit.ly/3xM7abc', 'suspicious'),
        ('https://login-verify.xyz/account/update', 'dangerous'),
        ('https://www.gooogle.com', 'suspicious'),  # typosquatting
    ]
    
    all_passed = True
    
    for url, expected_verdict in test_cases:
        verdict, reasons = analyze_url_heuristic(url)
        passed = verdict == expected_verdict
        details = f"Expected: {expected_verdict}, Got: {verdict}"
        print_test(f"Heuristic: {url[:50]}", passed, details)
        if not passed:
            all_passed = False
    
    return all_passed


# ──────────────────────────────────────────────
# Test 3: ML Model Loading
# ──────────────────────────────────────────────

def test_model_loading():
    """Test ML model loading."""
    print_section("TEST 3: ML Model Loading")
    
    # Check if model file exists
    model_path = "zyra_phishing_model.joblib"
    model_exists = os.path.exists(model_path)
    
    print_test("Model file exists", model_exists, f"Path: {model_path}")
    
    if not model_exists:
        print("\n⚠️  Model not found. Run 'python train_model.py' first.")
        return False
    
    # Try to load model
    loaded = load_model_once(model_path)
    print_test("Model loads successfully", loaded)
    
    if loaded:
        print_test("Model is marked as loaded", is_model_loaded())
    
    return loaded


# ──────────────────────────────────────────────
# Test 4: ML Inference
# ──────────────────────────────────────────────

def test_ml_inference():
    """Test ML inference."""
    print_section("TEST 4: ML Inference")
    
    if not is_model_loaded():
        print("⚠️  Skipping ML inference tests (model not loaded)")
        return False
    
    test_cases = [
        ('https://www.google.com', 'safe', '< 0.35'),
        ('http://192.168.1.1/login', 'dangerous', '>= 0.70'),
        ('https://bit.ly/3xM7abc', 'suspicious', '0.35-0.70'),
        ('https://login-verify.xyz/account/update', 'dangerous', '>= 0.70'),
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
# Test 5: End-to-End Integration
# ──────────────────────────────────────────────

def test_e2e_integration():
    """Test end-to-end integration."""
    print_section("TEST 5: End-to-End Integration")
    
    test_urls = [
        'https://www.google.com',
        'https://www.facebook.com',
        'http://192.168.1.1/login',
        'https://bit.ly/3xM7abc',
        'https://login-verify.xyz/account/update',
        'https://www.gooogle.com',
        'https://www.paypa1.com/login',
    ]
    
    all_passed = True
    
    for url in test_urls:
        try:
            verdict, reasons, metadata = analyze_link_ml_enhanced(url)
            
            # Check result structure
            has_verdict = verdict in ['safe', 'suspicious', 'dangerous']
            has_reasons = isinstance(reasons, list) and len(reasons) > 0
            has_metadata = isinstance(metadata, dict)
            has_method = 'method' in metadata
            
            passed = has_verdict and has_reasons and has_metadata and has_method
            
            details = f"Verdict: {verdict}, Method: {metadata.get('method')}, Reasons: {len(reasons)}"
            print_test(f"E2E: {url[:50]}", passed, details)
            
            if not passed:
                all_passed = False
            
        except Exception as e:
            print_test(f"E2E: {url[:50]}", False, f"Exception: {e}")
            all_passed = False
    
    return all_passed


# ──────────────────────────────────────────────
# Test 6: Performance Benchmark
# ──────────────────────────────────────────────

def test_performance():
    """Test performance benchmark."""
    print_section("TEST 6: Performance Benchmark")
    
    if not is_model_loaded():
        print("⚠️  Skipping performance tests (model not loaded)")
        return False
    
    print("\nRunning 100-iteration benchmark...")
    perf = benchmark_performance(n_iterations=100)
    
    if 'error' in perf:
        print_test("Performance benchmark", False, perf['error'])
        return False
    
    print(f"\nResults:")
    print(f"  Mean:   {perf['mean_ms']:.2f}ms")
    print(f"  Median: {perf['median_ms']:.2f}ms")
    print(f"  Min:    {perf['min_ms']:.2f}ms")
    print(f"  Max:    {perf['max_ms']:.2f}ms")
    print(f"  Std:    {perf['std_ms']:.2f}ms")
    print(f"  Under 30ms: {perf['under_30ms_pct']:.1f}%")
    
    passed = perf['mean_ms'] < 30
    print_test("Performance target (<30ms mean)", passed, 
              f"Mean: {perf['mean_ms']:.2f}ms")
    
    return passed


# ──────────────────────────────────────────────
# Test 7: Backward Compatibility
# ──────────────────────────────────────────────

def test_backward_compatibility():
    """Test backward compatibility with existing code."""
    print_section("TEST 7: Backward Compatibility")
    
    # Test that analyze_link_ml_enhanced returns correct format
    url = 'https://www.google.com'
    verdict, reasons, metadata = analyze_link_ml_enhanced(url)
    
    # Check return format matches old analyze_url
    passed = isinstance(verdict, str) and verdict in ['safe', 'suspicious', 'dangerous']
    passed = passed and isinstance(reasons, list)
    passed = passed and isinstance(metadata, dict)
    
    print_test("Return format compatibility", passed,
              f"Verdict: {verdict}, Reasons: {len(reasons)}, Metadata keys: {list(metadata.keys())}")
    
    return passed


# ──────────────────────────────────────────────
# Test 8: Voice Text Generation
# ──────────────────────────────────────────────

def test_voice_text():
    """Test voice-friendly text generation."""
    print_section("TEST 8: Voice Text Generation")
    
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
# Main Test Runner
# ──────────────────────────────────────────────

def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("  ZYRA ML LINK ANALYSIS — TEST SUITE")
    print("=" * 70)
    
    results = {}
    
    # Test 1: Feature extraction
    results['feature_extraction'] = test_feature_extraction()
    
    # Test 2: Heuristic analysis
    results['heuristic_analysis'] = test_heuristic_analysis()
    
    # Test 3: Model loading
    results['model_loading'] = test_model_loading()
    
    # Test 4: ML inference (only if model loaded)
    if results['model_loading']:
        results['ml_inference'] = test_ml_inference()
    else:
        print("\n⚠️  Skipping ML inference tests (model not loaded)")
        results['ml_inference'] = False
    
    # Test 5: E2E integration
    results['e2e_integration'] = test_e2e_integration()
    
    # Test 6: Performance (only if model loaded)
    if results['model_loading']:
        results['performance'] = test_performance()
    else:
        print("\n⚠️  Skipping performance tests (model not loaded)")
        results['performance'] = False
    
    # Test 7: Backward compatibility
    results['backward_compatibility'] = test_backward_compatibility()
    
    # Test 8: Voice text
    if results['model_loading']:
        results['voice_text'] = test_voice_text()
    else:
        print("\n⚠️  Skipping voice text tests (model not loaded)")
        results['voice_text'] = False
    
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
        traceback.print_exc()
        sys.exit(1)