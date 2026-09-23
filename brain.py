"""
brain.py — ZYRA Neural Core (AI brain)

The neural core behind all of Zyra's text conversations. The voice loop
(main.py), the FastAPI chat API (backend/zyra_bridge.py) and the desktop UI
bridge (desktop-ui/bridge_server.py) all drive this single module.

Improvements over the legacy brain:
  • Thread-safe conversation state — a reentrant lock makes concurrent chatter
    safe. Voice, web and UI callers never interleave or clobber context.
  • Automatic model discovery — uses ZYRA_OLLAMA_MODEL when it is installed,
    otherwise falls back to the best available installed model and reports the
    selection. No more hard failure when "llama3" is missing.
  • Environment configuration — model, Ollama host, temperature, token budget,
    history depth, timeout and the response-length cap are all tunable:
      ZYRA_OLLAMA_MODEL, ZYRA_OLLAMA_HOST, ZYRA_AI_TEMPERATURE,
      ZYRA_AI_NUM_PREDICT, ZYRA_AI_NUM_CTX, ZYRA_AI_MAX_HISTORY,
      ZYRA_AI_TIMEOUT_SECONDS, ZYRA_AI_MAX_RESPONSE_CHARS,
      ZYRA_AI_MEMORY (0 disables memory injection),
      ZYRA_AI_RESPONSE_BUDGET_SECONDS (hard reply deadline), ZYRA_AI_KEEP_ALIVE
  • Generous, realistic response window — every reply is given
    AI_RESPONSE_BUDGET_SECONDS (default 120s) to arrive. The budget is a
    safety net against a hung backend, not a 10s cut-off: CPU-only inference
    needs ~10s for a one-line phi3 answer and 30s+ for an 8B model such as
    llama3, so a reply is never abandoned while the model is still producing
    tokens. The HTTP timeout, the retry policy and the timeout fallback are
    all deadline-aware, and the model is kept warm (keep_alive) so no reply
    pays a cold-load penalty. Lower the budget (e.g.
    ZYRA_AI_RESPONSE_BUDGET_SECONDS=20) to fail fast instead of waiting.
  • Fast by design on CPU-only machines — the persona, remembered facts and
    history form a stable prompt prefix so Ollama can reuse its KV cache (the
    volatile clock moved to the latest user turn: measured prefill 7.8s →
    0.2s), answers are length-capped (ZYRA_AI_NUM_PREDICT, default 60) and the
    history is short (ZYRA_AI_MAX_HISTORY, default 6).
  • Token streaming — stream_ai() yields text as the model produces it, so a
    UI can show the first words in ~1-2s instead of waiting for the reply.
  • Long-term memory integration — remembered facts (memory.py) are injected
    into the system prompt every turn, so Zyra answers from what she knows about
    the user instead of hallucinating. Recall works directly from the store.
  • Retry with backoff for transient Ollama failures (429/500/503 + network
    noise), bounded by a hard client timeout.
  • Response hardening — ANSI/control characters are stripped and responses are
    capped to a sane length.

Backward-compatible API: ask_ai(question: str) -> response_text (str).
"""

import datetime
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

import ollama


# ──────────────────────────────────────────────
# Configuration (env-tunable)
# ──────────────────────────────────────────────

# Hard wall-clock budget for one AI reply — a safety net against a hung or
# unresponsive Ollama backend, NOT a 10s cut-off. CPU-only inference needs
# ~10s for a one-line phi3 answer and 30s+ for an 8B model such as llama3, so
# the default is generous (120s): a reply is never abandoned while the model
# is still generating. Tighten it (e.g. ZYRA_AI_RESPONSE_BUDGET_SECONDS=20)
# to fail fast instead of waiting.
try:
    AI_RESPONSE_BUDGET_SECONDS = max(
        1.0, float(os.environ.get("ZYRA_AI_RESPONSE_BUDGET_SECONDS", "120") or 120)
    )
except ValueError:  # unparsable override → keep the generous default
    AI_RESPONSE_BUDGET_SECONDS = 120.0

# HTTP timeout for the Ollama call itself. Defaults to the reply budget; an
# explicit ZYRA_AI_TIMEOUT_SECONDS is honoured but can never exceed the budget,
# so a hung request can never push a reply past the guaranteed window.
_timeout_env = os.environ.get("ZYRA_AI_TIMEOUT_SECONDS", "").strip()
try:
    _timeout_value = float(_timeout_env) if _timeout_env else AI_RESPONSE_BUDGET_SECONDS
except ValueError:
    _timeout_value = AI_RESPONSE_BUDGET_SECONDS
AI_TIMEOUT_SECONDS = max(1.0, min(_timeout_value, AI_RESPONSE_BUDGET_SECONDS))
# Short history: the whole conversation is re-sent every turn, and CPU prompt
# prefill is the single biggest latency cost (measured ~12 tok/s on a CPU-only
# box — a 330-token prompt costs ~28s when the KV cache is cold). 6 messages
# keeps the prompt small while preserving the immediate context.
MAX_HISTORY = int(os.environ.get("ZYRA_AI_MAX_HISTORY", "6"))
AI_TEMPERATURE = float(os.environ.get("ZYRA_AI_TEMPERATURE", "0.4"))
# Bounded generation: decode runs at ~4-10 tok/s on CPU, so 120 tokens could
# cost 15-30s on its own. 60 tokens keeps chat/voice answers to a few seconds
# (the persona also asks for 1-2 short sentences). Raise for longer replies.
AI_NUM_PREDICT = int(os.environ.get("ZYRA_AI_NUM_PREDICT", "60"))
# Context window: a ZYRA prompt is a few hundred tokens, so 2048 is plenty and
# the smaller KV cache keeps per-token attention cheap on CPU.
AI_NUM_CTX = int(os.environ.get("ZYRA_AI_NUM_CTX", "2048"))
AI_MAX_RESPONSE_CHARS = int(os.environ.get("ZYRA_AI_MAX_RESPONSE_CHARS", "3000"))
AI_MEMORY_ENABLED = os.environ.get("ZYRA_AI_MEMORY", "1").strip() not in ("0", "false", "False")
# Keep the model resident in Ollama memory so replies never pay a cold-load
# penalty (Ollama's default unload after ~5 idle minutes makes the next reply
# slow; a warm model answers in seconds).
AI_KEEP_ALIVE = os.environ.get("ZYRA_AI_KEEP_ALIVE", "30m").strip() or "30m"

_MAX_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 0.5
# The one-time model load at warm-up is allowed to take longer than a reply
# budget — its whole purpose is to absorb that cost outside the user window.
_WARMUP_TIMEOUT_SECONDS = max(120.0, AI_RESPONSE_BUDGET_SECONDS)

# Ordered fallback preferences (used only when the configured model is absent).
# Small, fast models come first: on a CPU-only machine prefill/decode scale with
# model size (measured here: tinyllama 1B ≈ 48 tok/s prefill, 9.5 tok/s decode;
# phi3 3.8B ≈ 12 tok/s prefill, 3.8 tok/s decode). Set ZYRA_OLLAMA_MODEL to
# override (e.g. "tinyllama" for maximum speed, "llama3" for more quality).
_PREFERRED_MODELS = [
    "phi3",
    "llama3.2",
    "qwen2.5",
    "mistral",
    "gemma",
    "tinyllama",
    "llama3",
    "llama3.1",
]

try:
    _ai_client = ollama.Client(timeout=AI_TIMEOUT_SECONDS)
except TypeError:  # very old ollama clients that don't accept `timeout`
    _ai_client = None


# ──────────────────────────────────────────────
# Persona / system-instruction blocks (kept from the legacy brain)
# ──────────────────────────────────────────────

try:
    from backend.link_security import SECURITY_ANALYST_PERSONA
except Exception:  # pragma: no cover - fallback if backend package not importable
    SECURITY_ANALYST_PERSONA = (
        "SECURITY ANALYSIS MODE: link inspection is handled by Zyra's backend "
        "security engine and returned as a text-only report. Do not fabricate "
        "analyses or touch the frontend dashboard UI for them."
    )

try:
    from nmap_handler import NMAP_PERSONA
except Exception:  # pragma: no cover - fallback if nmap module not importable
    NMAP_PERSONA = (
        "NETWORK SECURITY MODE: Zyra can perform network scanning using Nmap. "
        "When asked to scan networks or check for vulnerabilities, Zyra uses "
        "real Nmap scans to discover hosts, open ports, services, and security issues."
    )

# ──────────────────────────────────────────────
# Long-term memory (optional but always safe)
# ──────────────────────────────────────────────

try:
    from memory import all_memory as _memory_all
except Exception:  # pragma: no cover - memory module absent in odd environments
    _memory_all = None

# ──────────────────────────────────────────────
# Conversation state (thread-safe)
# ──────────────────────────────────────────────

_conversation_lock = threading.RLock()


def _base_system_prompt() -> str:
    """Stable persona block.

    IMPORTANT: this text must not change between turns — Ollama reuses the KV
    cache of an unchanged prompt prefix, and a shifting prefix forces a full
    re-prefill of the whole conversation (seconds lost on CPU).
    """
    return (
        "You are Zyra, a helpful, intelligent, friendly AI assistant. "
        "Answer in 1-2 short sentences (under 40 words) and get straight to "
        "the point; only write more when the user explicitly asks for detail. "
        + SECURITY_ANALYST_PERSONA
        + " "
        + NMAP_PERSONA
    )


def _build_system_prompt(memory_digest: str, now: Optional[datetime.datetime] = None) -> str:
    """Build the cached system prompt (persona + remembered facts).

    The volatile date/time is deliberately NOT part of this block: it used to
    change every minute, which invalidated Ollama's prompt cache and forced a
    full re-prefill of the conversation on every turn (measured: 7.8s prefill
    cold vs 0.2s with a stable prefix). The live timestamp is stamped onto the
    current user turn by _payload_snapshot() instead, i.e. after the cached
    prefix.

    ``now`` must be resolved inside this function (defaults to today); only the
    date is used so the block stays stable for the whole day.
    """
    now = now or datetime.datetime.now()
    parts = [_base_system_prompt()]
    # Day-granularity clock: safe to cache. A minute-level timestamp here
    # changed the prompt every 60s and forced Ollama to re-prefill the whole
    # conversation each turn (measured 7.8s vs 0.2s prefill); a date changes
    # once a day, so the cached prefix survives every turn in between.
    parts.append(f"Today's date is {now:%Y-%m-%d}.")
    if memory_digest:
        parts.append(
            "Memorized facts about the user (prefer these exact facts over any "
            "guess; if nothing here answers the question, say you don't know):\n"
            + memory_digest
        )
    return "\n\n".join(p for p in parts if p)


conversation: List[Dict[str, str]] = [
    {"role": "system", "content": _build_system_prompt("")},
]


def _refresh_system_locked(system_text: str) -> None:
    if not conversation:
        conversation.append({"role": "system", "content": system_text})
    else:
        conversation[0]["content"] = system_text


def _prune_locked() -> None:
    """Keep the system slot plus the N most recent messages."""
    if len(conversation) > MAX_HISTORY + 1:
        conversation[:] = [conversation[0]] + conversation[-MAX_HISTORY:]


def clear_conversation() -> None:
    """Start a fresh conversation (keeps the system/persona slot)."""
    with _conversation_lock:
        conversation[:] = [
            {"role": "system", "content": _build_system_prompt("")},
        ]


def get_conversation() -> List[Dict[str, str]]:
    """Return a snapshot copy of the current conversation (for debugging/UIs)."""
    with _conversation_lock:
        return [dict(m) for m in conversation]


def _payload_snapshot() -> List[Dict[str, str]]:
    """Return a byte-identical snapshot of the conversation for Ollama.

    Byte-exactness is what makes the KV cache reusable: Ollama reuses the
    longest common prefix between requests, so anything that rewrites history
    (stamping a clock into the prompt, trimming the stored answer, reordering
    messages) invalidates the cache and forces a full re-prefill of the whole
    conversation — measured 7.8s cold vs 0.2s cached prefill. Whatever is sent
    must therefore be exactly what is stored in ``conversation``.
    """
    with _conversation_lock:
        return [dict(m) for m in conversation]


# ──────────────────────────────────────────────
# Ollama client & model management
# ──────────────────────────────────────────────

def _make_client():
    """Build an ollama client honouring the configured host + timeout."""
    host = os.environ.get("ZYRA_OLLAMA_HOST", "").strip() or None
    client_kwargs: Dict[str, Any] = {"timeout": AI_TIMEOUT_SECONDS}
    if host:
        client_kwargs["host"] = host
    try:
        return ollama.Client(**client_kwargs)
    except TypeError:  # pragma: no cover - ancient client without `timeout`
        return ollama.Client() if not host else None


def _get_client():
    """Return the shared client, lazily creating one if the import-time
    construction fell back to None (old client or host override)."""
    global _ai_client
    if _ai_client is None:
        _ai_client = _make_client()
    return _ai_client


def _basename(model: str) -> str:
    """Strip a tag from a model name ("llama3:8b" -> "llama3")."""
    return model.split(":")[0].strip()


def available_models() -> List[str]:
    """Chat models currently installed in Ollama (best effort, never raises)."""
    try:
        sender = _get_client() or ollama
        info = sender.list()
    except Exception:
        return []
    models = []
    for entry in info.get("models", []):
        name = entry.get("name") or entry.get("model") or ""
        if name and name not in models:
            models.append(name)
    return models


def _select_model() -> str:
    """Pick the model to use from this run.

    1. The configured ZYRA_OLLAMA_MODEL if it (or its base) is installed.
    2. With no explicit configuration, the first installed model from the
       speed-ordered preferred list (keeps replies inside the time budget —
       a cold/warm 8B model cannot finish within 5-10s on typical hardware).
    3. The first installed model from the preferred fallback list.
    4. Any installed model.
    5. The configured default, even if we cannot verify it right now.
    """
    requested = os.environ.get("ZYRA_OLLAMA_MODEL", "").strip()
    installed = available_models()
    if not installed:
        return requested or _PREFERRED_MODELS[0]
    if requested:
        requested_base = _basename(requested)
        for name in installed:
            if _basename(name) == requested_base:
                return name
    for candidate in _PREFERRED_MODELS:
        for name in installed:
            if _basename(name) == candidate:
                return name
    return installed[0]


_ACTIVE_MODEL = _select_model()


def get_model() -> str:
    """The model name currently in use."""
    return _ACTIVE_MODEL


def set_model(name: str) -> str:
    """Override the model used by future calls. Returns the active model."""
    global _ACTIVE_MODEL
    requested = str(name or "").strip()
    if requested:
        _ACTIVE_MODEL = requested
        print(f"brain: model set to '{_ACTIVE_MODEL}'")
    return _ACTIVE_MODEL


# ──────────────────────────────────────────────
# Memory integration
# ──────────────────────────────────────────────

def _memory_digest(max_facts: int = 8) -> str:
    """Build a compact, capped digest of remembered facts for the system prompt."""
    if not AI_MEMORY_ENABLED or _memory_all is None:
        return ""
    try:
        data = _memory_all()
    except Exception:
        return ""
    if not data:
        return ""
    lines = []
    for key, value in list(data.items())[:max_facts]:
        try:
            text = str(value).replace("\n", " ").strip()[:120]
        except Exception:  # pragma: no cover - defensive
            text = ""
        lines.append(f"- {key}: {text}")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Response hardening & error handling
# ──────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _sanitize_answer(text: Any) -> str:
    """Strip ANSI/control characters, trim, and cap the response length."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = _ANSI_RE.sub("", text)
    text = "".join(ch for ch in text if ord(ch) >= 32 or ch in "\n\t")
    text = text.strip()
    if len(text) > AI_MAX_RESPONSE_CHARS:
        text = text[:AI_MAX_RESPONSE_CHARS].rstrip() + "…"
    return text


def _raw_content(response: Any) -> str:
    """The model's exact text, unmodified.

    History stores this verbatim so the next request replays a byte-identical
    prompt and Ollama can reuse its KV cache (see _payload_snapshot).
    """
    try:
        content = response["message"]["content"]
    except (KeyError, TypeError, AttributeError):
        return ""
    return content if isinstance(content, str) else str(content or "")


def _extract_answer(response: Any) -> str:
    """Pull the assistant text out of an Ollama chat response (display-safe)."""
    answer = _sanitize_answer(_raw_content(response))
    if not answer:
        answer = "I didn't get a response from the model this time. Please try again."
    return answer


def _friendly_ollama_error(exc: BaseException) -> str:
    """Turn an ollama.ResponseError into a natural, actionable Zyra message."""
    status = getattr(exc, "status_code", None)
    model = get_model()
    if status == 404:
        return (
            f"I couldn't find the '{model}' model in Ollama. "
            f"Please install it with 'ollama pull {model}' and try again."
        )
    text = str(exc) or "unknown Ollama error"
    lowered = text.lower()
    if "connection" in lowered or "connect" in lowered or "refused" in lowered:
        return (
            "I'm having trouble connecting to the AI model. "
            "Please make sure Ollama is running (ollama serve) and try again."
        )
    if "load" in lowered or "unavailable" in lowered:
        return "The AI model is still loading. Give me a moment and try again."
    return (
        "Sorry, I'm having trouble connecting to the AI model. "
        f"Please try again in a moment. (Ollama: {text!r})"
    )


def _friendly_failure(exc: BaseException) -> str:
    """Fast, honest message for a backend that timed out or failed outright."""
    if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
        return (
            f"The model was still thinking after my "
            f"{AI_RESPONSE_BUDGET_SECONDS:.0f}-second reply budget, so I stopped "
            "waiting. Please send that again — a warm model answers in seconds."
        )
    return (
        "Sorry, something went wrong. Please make sure Ollama is running "
        "and try again."
    )


# ──────────────────────────────────────────────
# Core chat runner (retry + backoff)
# ──────────────────────────────────────────────

def _run_chat(messages: List[Dict[str, str]]) -> Any:
    """Invoke Ollama within the hard reply budget.

    A deadline is enforced across attempts: the first call gets the whole
    budget and the single retry only happens when enough of it is left, so
    the total wall time never exceeds AI_RESPONSE_BUDGET_SECONDS. Raises the
    original final exception on persistent failure; ask_ai converts it into
    a friendly message.
    """
    sender = _get_client() or ollama
    chat_kwargs = {
        "model": _ACTIVE_MODEL,
        "messages": messages,
        "keep_alive": AI_KEEP_ALIVE,
        "options": {
            "temperature": AI_TEMPERATURE,
            "num_predict": AI_NUM_PREDICT,
            "num_ctx": AI_NUM_CTX,
        },
    }
    deadline = time.monotonic() + AI_RESPONSE_BUDGET_SECONDS
    last_exc: Optional[BaseException] = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return sender.chat(**chat_kwargs)
        except ollama.ResponseError as exc:
            status = getattr(exc, "status_code", None)
            # 429/500/503 are transient (rate limit / model still loading);
            # 404 means the model is not pulled and will not fix itself.
            if attempt == 0 and status in (429, 500, 503):
                last_exc = exc
            else:
                raise
        except Exception as exc:  # noqa: BLE001 - retry once on network noise
            last_exc = exc
        # Never retry when the reply budget is already spent (a timeout means
        # the whole window is gone — retrying would double the wait).
        remaining = deadline - time.monotonic()
        if attempt + 1 >= _MAX_ATTEMPTS or remaining < 1.0:
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("chat failed")
        time.sleep(min(_RETRY_DELAY_SECONDS, max(0.0, remaining - 0.5)))
    raise RuntimeError("chat failed")


# ──────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────

def ask_ai(question) -> str:
    """Ask the AI a question and get a response.

    Thread-safe: guards the shared conversation with a reentrant lock so voice,
    web and UI callers can interleave safely. Long-term memory facts are
    automatically injected into the system prompt for context.

    The call blocks for as long as the model needs, bounded by
    AI_RESPONSE_BUDGET_SECONDS (default 120s) — async callers must therefore
    run it in a worker thread so the event loop stays responsive.
    """
    if not question or not str(question).strip():
        return "Please say something!"

    question = str(question).strip()
    system_text = _build_system_prompt(_memory_digest())

    with _conversation_lock:
        _refresh_system_locked(system_text)
        conversation.append({"role": "user", "content": question})
        _prune_locked()

    started = time.monotonic()
    try:
        # Pass a snapshot so the in-flight Ollama request can never see the
        # shared thread-safe conversation mutate under it mid-generation.
        response = _run_chat(_payload_snapshot())
    except ollama.ResponseError as exc:
        print(f"brain: Ollama error: {exc}")
        with _conversation_lock:
            _prune_locked()
        return _friendly_ollama_error(exc)
    except Exception as exc:
        elapsed = time.monotonic() - started
        print(f"brain: AI error after {elapsed:.1f}s: {exc}")
        with _conversation_lock:
            _prune_locked()
        # A timeout means the backend hung for the whole reply budget — say so
        # instead of leaving the user staring at a typing indicator.
        return _friendly_failure(exc)

    raw_answer = _raw_content(response)
    answer = _sanitize_answer(raw_answer) or (
        "I didn't get a response from the model this time. Please try again."
    )
    elapsed = time.monotonic() - started
    print(f"brain: reply in {elapsed:.2f}s ({len(answer)} chars, model={get_model()})")

    with _conversation_lock:
        # Store the model's exact text (not the display-sanitized copy): the
        # next turn replays it, and any rewrite would break the cached prompt
        # prefix and cost a full re-prefill.
        conversation.append({"role": "assistant", "content": raw_answer or answer})
        _prune_locked()

    return answer


def stream_ai(question):
    """Stream an answer token-by-token (generator).

    Same thread-safe conversation state, prompt-cache hygiene and error
    handling as ask_ai(), but chunks of text are yielded as Ollama produces
    them so a UI can show the first words in ~1-2s instead of waiting for the
    full reply. The complete, sanitized answer is appended to the conversation
    when the stream finishes.

    Yields:
        str: successive pieces of the answer (empty pieces are skipped).
    """
    if not question or not str(question).strip():
        yield "Please say something!"
        return

    question = str(question).strip()
    with _conversation_lock:
        _refresh_system_locked(_build_system_prompt(_memory_digest()))
        conversation.append({"role": "user", "content": question})
        _prune_locked()

    started = time.monotonic()
    sender = _get_client() or ollama
    chat_kwargs = {
        "model": _ACTIVE_MODEL,
        "messages": _payload_snapshot(),
        "keep_alive": AI_KEEP_ALIVE,
        "stream": True,
        "options": {
            "temperature": AI_TEMPERATURE,
            "num_predict": AI_NUM_PREDICT,
            "num_ctx": AI_NUM_CTX,
        },
    }

    pieces: List[str] = []
    try:
        for chunk in sender.chat(**chat_kwargs):
            try:
                piece = (chunk.get("message") or {}).get("content") or ""
            except (AttributeError, TypeError):
                piece = ""
            if piece:
                pieces.append(piece)
                yield piece
    except ollama.ResponseError as exc:
        print(f"brain: Ollama stream error: {exc}")
        if not pieces:
            yield _friendly_ollama_error(exc)
            return
    except Exception as exc:  # noqa: BLE001 - report instead of raising mid-stream
        elapsed = time.monotonic() - started
        print(f"brain: AI stream error after {elapsed:.1f}s: {exc}")
        if not pieces:
            yield _friendly_failure(exc)
            return

    raw_answer = "".join(pieces)
    answer = _sanitize_answer(raw_answer)
    if not answer:
        answer = "I didn't get a response from the model this time. Please try again."
        yield answer
    print(
        f"brain: streamed reply in {time.monotonic() - started:.2f}s "
        f"({len(answer)} chars, model={get_model()})"
    )
    with _conversation_lock:
        # Byte-exact history keeps the prompt prefix cacheable next turn.
        conversation.append({"role": "assistant", "content": raw_answer or answer})
        _prune_locked()

def _warmup_client():
    """A dedicated client with a generous timeout for the one-time model load.

    The budgeted client would abort a cold model load after 10s; warm-up
    exists precisely to pay that cost up front, off the user's clock.
    """
    host = os.environ.get("ZYRA_OLLAMA_HOST", "").strip() or None
    client_kwargs: Dict[str, Any] = {"timeout": _WARMUP_TIMEOUT_SECONDS}
    if host:
        client_kwargs["host"] = host
    try:
        return ollama.Client(**client_kwargs)
    except TypeError:  # pragma: no cover - ancient client without `timeout`
        return None


def warm_up_model() -> bool:
    """Preload the active model into Ollama memory so the first real reply
    is fast.

    Best effort and never raises — safe to call from a background thread at
    server startup. Returns True when the model is loaded and resident
    (keep_alive keeps it that way between requests).
    """
    try:
        sender = _warmup_client() or _get_client() or ollama
        started = time.monotonic()
        sender.generate(model=_ACTIVE_MODEL, prompt="", keep_alive=AI_KEEP_ALIVE)
        print(
            f"brain: model '{_ACTIVE_MODEL}' warmed up in "
            f"{time.monotonic() - started:.1f}s (kept alive {AI_KEEP_ALIVE})"
        )
        return True
    except Exception as exc:  # noqa: BLE001 - warm-up is optional
        print(f"brain: warm-up skipped ({exc})")
        return False


def warm_up_async() -> None:
    """Kick off warm_up_model() in a daemon thread (fire-and-forget)."""
    threading.Thread(target=warm_up_model, name="zyra-model-warmup", daemon=True).start()


__all__ = [
    "ask_ai",
    "stream_ai",
    "available_models",
    "clear_conversation",
    "get_conversation",
    "get_model",
    "set_model",
    "conversation",
    "warm_up_model",
    "warm_up_async",
    "MAX_HISTORY",
    "AI_TIMEOUT_SECONDS",
    "AI_RESPONSE_BUDGET_SECONDS",
    "AI_NUM_PREDICT",
    "AI_NUM_CTX",
]


# ──────────────────────────────────────────────
# Standalone smoke test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print(f"brain: active model = {get_model()}")
    print(f"brain: installed models = {available_models()}")
    print(f"brain: memory digest = {_memory_digest()!r}")
    print("brain: ask_ai('Say hi in one short sentence.') ->")
    print(ask_ai("Say hi in one short sentence."))