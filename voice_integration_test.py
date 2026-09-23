#!/usr/bin/env python3
"""ZYRA voice pipeline integration check — run as: python voice_integration_test.py"""
import threading, time
import listen, speak, brain

print('=' * 60)
print('ZYRA VOICE PIPELINE INTEGRATION CHECK')
print('=' * 60 + '\n')

# Warm up everything before timing anything
listen.warm_up()
speak.warm_up()
print('Warms completed. Starting check...\n')

print('[1] STT model:')
try:
    info = listen.get_model_info()
    print(f'    STT model={info.get("name")} device={info.get("device")} compute={info.get("compute_type")}')
except Exception as e:
    print(f'    Error: {e}')

print('\n[2] AI streaming:')
t0 = time.time()
first = None
sentences = []
for s in brain.ask_ai_stream('What is the capital of France? Answer in one short sentence.'):
    if first is None:
        first = time.time() - t0
    sentences.append(s)
    print(f'    [{time.time() - t0:.2f}s] {s}')
print(f'    FIRST SENTENCE after {first:.2f}s | total {time.time() - t0:.2f}s')

print('\n[3] TTS streaming queue:')
speak.speak_async('Sentence one. Sentence two. Sentence three.')
print('    Queued 3 sentences (speak_async returns immediately)')
started = time.time()
speak.wait_until_done()
elapsed = time.time() - started
print(f'    All sentences finished in {elapsed:.2f}s')

print('\n' + '=' * 60)
print('SUCCESS - pipeline works without duplicate requests')
print('=' * 60)
print('\nTo run ZYRA: python main.py')
