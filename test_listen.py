#!/usr/bin/env python3
"""
Test script to verify listen.py functionality
"""
import sys

print("Testing listen.py module...")
print("-" * 50)

try:
    import listen
    print("✅ listen module imported successfully")
    
    # Test that the listen function exists
    if hasattr(listen, 'listen'):
        print("✅ listen() function found")
    else:
        print("❌ listen() function not found")
        sys.exit(1)
    
    print("\n✅ All basic checks passed!")
    print("\nNote: To test actual listening, run: python test_listen.py")
    print("The script will listen for 10 seconds and attempt speech recognition.")
    
    # Ask if user wants to test
    response = input("\nDo you want to test listening now? (y/n): ").lower()
    if response == 'y':
        print("\n🎤 Starting listening test...")
        print("Speak something within 10 seconds...")
        result = listen.listen()
        if result:
            print(f"\n✅ Recognized speech: '{result}'")
        else:
            print("\n❌ No speech detected or recognition failed")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)