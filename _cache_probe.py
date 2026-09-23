"""_cache_probe.py — temporary probe to find what breaks Ollama's prompt cache.

1) Does an assistant turn that is not byte-identical to what the model produced
   force a full prompt re-evaluation on the next turn?
2) How fast / how coherent is tinyllama (1B) compared with phi3 (3.8B) for the
   short answers ZYRA needs?
Temporary diagnostic — safe to delete.
"""
import time

import ollama

CLIENT = ollama.Client(timeout=300)
SYS = {"role": "system", "content": "You are Zyra, a helpful assistant. Answer in one short sentence."}
OPTS = {"temperature": 0.4, "num_predict": 40, "num_ctx": 2048}


def call(model, messages):
    started = time.monotonic()
    response = CLIENT.chat(model=model, messages=messages, keep_alive="30m", options=OPTS)
    wall = time.monotonic() - started
    return wall, response


def report(tag, wall, response):
    print(
        f"  {tag:<26} {wall:6.2f}s  prompt_eval {response.get('prompt_eval_count'):>4} tok "
        f"in {response.get('prompt_eval_duration', 0) / 1e6:7.0f}ms  "
        f"decode {response.get('eval_count'):>3} tok"
    )


def probe_cache(model):
    print(f"cache probe on {model}:")
    u1 = {"role": "user", "content": "Say hi in one short sentence."}
    wall1, r1 = call(model, [SYS, u1])
    report("turn1 (fresh)", wall1, r1)
    raw = r1["message"]["content"]
    print(f"    raw assistant text = {raw!r}")

    wall2, r2 = call(model, [SYS, u1, {"role": "assistant", "content": raw},
                             {"role": "user", "content": "Name one colour."}])
    report("turn2 (raw history)", wall2, r2)

    wall3, r3 = call(model, [SYS, u1, {"role": "assistant", "content": raw.strip()},
                             {"role": "user", "content": "Name one animal."}])
    report("turn3 (stripped history)", wall3, r3)

    wall4, r4 = call(model, [SYS, u1, {"role": "assistant", "content": raw},
                             {"role": "user", "content": "Name one animal."}])
    report("turn4 (same history again)", wall4, r4)


def probe_quality(model):
    print(f"speed/quality on {model}:")
    for question in ["What is 2 plus 3?", "Name one colour.", "Say hi in one short sentence."]:
        started = time.monotonic()
        response = CLIENT.chat(model=model, messages=[SYS, {"role": "user", "content": question}],
                               keep_alive="30m", options=OPTS)
        wall = time.monotonic() - started
        print(f"  {wall:6.2f}s  {response.get('eval_count')} tok  {response['message']['content'][:90]!r}")


if __name__ == "__main__":
    probe_cache("phi3")
    probe_quality("tinyllama")
