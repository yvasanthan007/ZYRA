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
      ZYRA_AI_MAX_RESPONSE_CHARS, ZYRA_AI_MEMORY (0 disables memory injection)
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

# Bound the AI call so a slow or hung Ollama backend can never stall the
# dashboard chat forever (the ollama client's default timeout is much longer).
AI_TIMEOUT_SECONDS = float(os.environ.get("ZYRA_AI_TIMEOUT_SECONDS", "120"))
MAX_HISTORY = int(os.environ.get("ZYRA_AI_MAX_HISTORY", "10"))
AI_TEMPERATURE = float(os.environ.get("ZYRA_AI_TEMPERATURE", "0.4"))
AI_NUM_PREDICT = int(os.environ.get("ZYRA_AI_NUM_PREDICT", "200"))
AI_MAX_RESPONSE_CHARS = int(os.environ.get("ZYRA_AI_MAX_RESPONSE_CHARS", "3000"))
AI_MEMORY_ENABLED = os.environ.get("ZYRA_AI_MEMORY", "1").strip() not in ("0", "false", "False")

_MAX_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 1.2

# Ordered fallback preferences (used only when the configured model is absent).
_PREFERRED_MODELS = [
    "llama3",
    "llama3.2",
    "llama3.1",
    "mistral",
    "gemma",
    "phi3",
    "qwen2.5",
    "tinyllama",
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
        "Answer naturally and briefly unless the user asks for more details. "
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
    2. The first installed model from the preferred fallback list.
    3. Any installed model.
    4. The configured default, even if we cannot verify it right now.
    """
    requested = os.environ.get("ZYRA_OLLAMA_MODEL", "").strip() or "llama3"
    installed = available_models()
    if not installed:
        return requested
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

def _run_chat(messages: List[Dict[str, str]]) -> Any:
    """Invoke Ollama, retrying transient failures with backoff.

    Raises the original final exception on persistent failure; ask_ai converts
    it into a friendly message.
    """
    sender = _get_client() or ollama
    chat_kwargs = {
        "model": _ACTIVE_MODEL,
        "messages": messages,
        "options": {
            "temperature": AI_TEMPERATURE,
            "num_predict": AI_NUM_PREDICT,
        },
    }
    last_exc: Optional[BaseException] = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return sender.chat(**chat_kwargs)
        except ollama.ResponseError as exc:
            status = getattr(exc, "status_code", None)
            # 429/500/503 are transient (rate limit / model still loading);
            # 404 means the model is not pulled and will not fix itself.
            if attempt == 0 and status in (429, 500, 503):
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            raise
        except Exception as exc:  # noqa: BLE001 - retry once on network noise
            last_exc = exc
            if attempt == 0:
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            raise
    if last_exc is not None:
        raise last_exc
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
        print(f"brain: AI error: {exc}")
        with _conversation_lock:
            _prune_locked()
        return (
            "Sorry, something went wrong. Please make sure Ollama is running "
            "and try again."
        )

    answer = _extract_answer(response)

    with _conversation_lock:
        conversation.append({"role": "assistant", "content": answer})
        _prune_locked()

    return answer


__all__ = [
    "ask_ai",
    "available_models",
    "clear_conversation",
    "get_conversation",
    "get_model",
    "set_model",
    "conversation",
    "MAX_HISTORY",
    "AI_TIMEOUT_SECONDS",
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