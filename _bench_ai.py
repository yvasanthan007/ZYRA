"""_bench_ai.py — temporary latency benchmark for ZYRA's AI brain.

Prints where each turn's wall time goes (model load / prompt prefill / token
decode) plus a streaming time-to-first-token measurement. Temporary tool used
to validate the low-latency changes; safe to delete.
"""
import os
import time

os.environ.pop("ZYRA_AI_RESPONSE_BUDGET_SECONDS", None)

import brain  # noqa: E402  (import after env cleanup)


def turn(question):
    with brain._conversation_lock:
        brain._refresh_system_locked(brain._build_system_prompt(brain._memory_digest()))
        brain.conversation.append({"role": "user", "content": question})
        brain._prune_locked()
    started = time.monotonic()
    response = brain._run_chat(brain._payload_snapshot())
    wall = time.monotonic() - started
    load_ms = response.get("load_duration", 0) / 1e6
    pre_tok = response.get("prompt_eval_count")
    pre_ms = response.get("prompt_eval_duration", 0) / 1e6
    out_tok = response.get("eval_count")
    ev_ms = response.get("eval_duration", 0) / 1e6
    print(
        f"  {wall:6.2f}s wall | load {load_ms:7.0f}ms | prefill {pre_tok:>4} tok "
        f"{pre_ms:7.0f}ms ({pre_tok / max(pre_ms, 1) * 1000:5.1f} tok/s) | "
        f"decode {out_tok:>3} tok {ev_ms:7.0f}ms ({out_tok / max(ev_ms, 1) * 1000:4.1f} tok/s)"
    )
    answer = response["message"]["content"]
    with brain._conversation_lock:
        brain.conversation.append({"role": "assistant", "content": answer})
        brain._prune_locked()
    print(f"         -> {answer[:70]!r}")
    return wall


def main():
    print(f"model={brain.get_model()} history={brain.MAX_HISTORY} "
          f"num_predict={brain.AI_NUM_PREDICT} num_ctx={brain.AI_NUM_CTX}")
    brain.clear_conversation()
    print("non-streaming turns:")
    for question in [
        "Say hi in one short sentence.",
        "What is 2 plus 3?",
        "Name one color.",
        "Thanks!",
    ]:
        turn(question)

    print("streaming turn (time to first token):")
    brain.clear_conversation()
    started = time.monotonic()
    first = None
    chars = 0
    for piece in brain.stream_ai("Say hi in one short sentence."):
        if first is None:
            first = time.monotonic() - started
        chars += len(piece)
    print(f"  first token in {first:.2f}s | full reply {chars} chars in "
          f"{time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
