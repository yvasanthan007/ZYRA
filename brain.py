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
      ZYRA_AI_NUM_PREDICT, ZYRA_AI_MAX_HISTORY, ZYRA_AI_TIMEOUT_SECONDS,
      ZYRA_AI_MAX_RESPONSE_CHARS, ZYRA_AI_MEMORY (0 disables memory injection),
      ZYRA_AI_RESPONSE_BUDGET_SECONDS (hard reply deadline), ZYRA_AI_KEEP_ALIVE
  • Guaranteed response window — every reply is forced to arrive within
    AI_RESPONSE_BUDGET_SECONDS (default 10s): the HTTP timeout, the retry
    policy and the timeout fallback are all deadline-aware, and the model is
    kept warm (keep_alive) so no reply ever pays a cold-load penalty.
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

# Hard wall-clock budget for one AI reply. Every chat/voice answer is forced
# to arrive within this window (default 10s → "response within 5-10 seconds").
AI_RESPONSE_BUDGET_SECONDS = float(os.environ.get("ZYRA_AI_RESPONSE_BUDGET_SECONDS", "10"))

# HTTP timeout for the Ollama call itself. Defaults to the reply budget; an
# explicit ZYRA_AI_TIMEOUT_SECONDS is honoured but can never exceed the budget,
# so a hung request can never push a reply past the guaranteed window.
_timeout_env = os.environ.get("ZYRA_AI_TIMEOUT_SECONDS", "").strip()
try:
    _timeout_value = float(_timeout_env) if _timeout_env else AI_RESPONSE_BUDGET_SECONDS
except ValueError:
    _timeout_value = AI_RESPONSE_BUDGET_SECONDS
AI_TIMEOUT_SECONDS = max(1.0, min(_timeout_value, AI_RESPONSE_BUDGET_SECONDS))
MAX_HISTORY = int(os.environ.get("ZYRA_AI_MAX_HISTORY", "10"))
AI_TEMPERATURE = float(os.environ.get("ZYRA_AI_TEMPERATURE", "0.4"))
# Fewer max tokens ⇒ generation finishes well inside the budget (200 tokens
# can take 10-20s on CPU; 120 keeps answers brief and fast).
AI_NUM_PREDICT = int(os.environ.get("ZYRA_AI_NUM_PREDICT", "120"))
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
_WARMUP_TIMEOUT_SECONDS = 120.0

# Ordered fallback preferences (used only when the configured model is absent).
# Small, fast models come first: they keep every reply inside the 5-10s budget
# on typical machines (a cold/warm 8B model cannot).
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
    return (
        "You are Zyra, a helpful, intelligent, friendly AI assistant. "
        "Reply in 1-3 short sentences and get straight to the point; only "
        "write more when the user explicitly asks for detail. "
        + SECURITY_ANALYST_PERSONA
        + " "
        + NMAP_PERSONA
    )


def _build_system_prompt(memory_digest: str, now: Optional[datetime.datetime] = None) -> str:
    now = now or datetime.datetime.now()
    parts = [_base_system_prompt()]
    try:
        tz_name = now.astimezone().tzname()
    except Exception:  # pragma: no cover - defensive
        tz_name = ""
    parts.append(f"Current date: {now:%Y-%m-%d %H:%M} {tz_name or ''}".rstrip())
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


def _extract_answer(response: Any) -> str:
    """Pull the assistant text out of an Ollama chat response."""
    try:
        content = response["message"]["content"]
    except (KeyError, TypeError, AttributeError):
        content = ""
    answer = _sanitize_answer(content)
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


# ──────────────────────────────────────────────
# Core chat runner (retry + backoff)
# ──────────────────────────────────────────────

def _reselect_missing_model(chat_kwargs: Dict[str, Any]) -> bool:
    """Re-discover installed models after a 404 'model not found'.

    _ACTIVE_MODEL is frozen at import time; if Ollama was unreachable then
    (or the model was removed later) every chat fails with a 404. Re-running
    the selection now lets ZYRA heal itself by switching to a model that is
    actually installed. Returns True when a different model was picked.
    """
    global _ACTIVE_MODEL
    previous = _ACTIVE_MODEL
    try:
        candidate = _select_model()
    except Exception:  # noqa: BLE001 - selection is best effort
        return False
    if not candidate or candidate == previous:
        return False
    print(f"brain: model '{previous}' not found — switching to '{candidate}'")
    _ACTIVE_MODEL = candidate
    chat_kwargs["model"] = candidate
    return True


def _run_chat(messages: List[Dict[str, str]]) -> Any:
    """Invoke Ollama within the hard reply budget.

    A deadline is enforced across attempts: the first call gets the whole
    budget and the single retry only happens when enough of it is left, so
    the total wall time never exceeds AI_RESPONSE_BUDGET_SECONDS. A 404
    (stale model pick) triggers one re-discovery + retry instead of failing.
    Raises the original final exception on persistent failure; ask_ai
    converts it into a friendly message.
    """
    sender = _get_client() or ollama
    chat_kwargs = {
        "model": _ACTIVE_MODEL,
        "messages": messages,
        "keep_alive": AI_KEEP_ALIVE,
        "options": {
            "temperature": AI_TEMPERATURE,
            "num_predict": AI_NUM_PREDICT,
        },
    }
    deadline = time.monotonic() + AI_RESPONSE_BUDGET_SECONDS
    last_exc: Optional[BaseException] = None
    reselected = False
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return sender.chat(**chat_kwargs)
        except ollama.ResponseError as exc:
            status = getattr(exc, "status_code", None)
            # 429/500/503 are transient (rate limit / model still loading).
            # 404 means the model is missing: re-discover what IS installed
            # and retry once with that instead of hard-failing.
            if attempt == 0 and status == 404 and _reselect_missing_model(chat_kwargs):
                reselected = True
            elif attempt == 0 and status in (429, 500, 503):
                last_exc = exc
            else:
                raise
        except Exception as exc:  # noqa: BLE001 - retry once on network noise
            last_exc = exc
        # Never retry when the reply budget is already spent (a timeout means
        # the whole window is gone — retrying would double the wait).
        remaining = deadline - time.monotonic()
        can_retry = attempt + 1 < _MAX_ATTEMPTS and remaining >= 1.0
        if not can_retry or (last_exc is None and not reselected):
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
    """
    if not question or not str(question).strip():
        return "Please say something!"

    question = str(question).strip()
    system_text = _build_system_prompt(_memory_digest(), datetime.datetime.now())

    with _conversation_lock:
        _refresh_system_locked(system_text)
        conversation.append({"role": "user", "content": question})
        _prune_locked()

    started = time.monotonic()
    try:
        # Pass a snapshot so the in-flight Ollama request can never see the
        # shared thread-safe conversation mutate under it mid-generation.
        response = _run_chat(list(conversation))
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
        # A timeout means the reply budget was spent — answer fast and honestly
        # instead of leaving the user staring at a typing indicator.
        if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            return (
                f"That took longer than my {AI_RESPONSE_BUDGET_SECONDS:.0f}-second "
                "reply budget, so I stopped waiting. Please try again — "
                "I'm usually much faster."
            )
        return (
            "Sorry, something went wrong. Please make sure Ollama is running "
            "and try again."
        )

    answer = _extract_answer(response)
    elapsed = time.monotonic() - started
    print(f"brain: reply in {elapsed:.2f}s ({len(answer)} chars, model={get_model()})")

    with _conversation_lock:
        conversation.append({"role": "assistant", "content": answer})
        _prune_locked()

    return answer


# ──────────────────────────────────────────────
# Model warm-up (removes the cold-start penalty)
# ──────────────────────────────────────────────

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