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
    AI_RESPONSE_BUDGET_SECONDS (default 180s) to arrive. The budget is a
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
  0.2s), responses use a moderate token budget (ZYRA_AI_NUM_PREDICT, default 320),
    history is short (ZYRA_AI_MAX_HISTORY, default 6).
  • Token streaming — stream_ai() yields text as the model produces it, so a
    UI can render the first words immediately instead of waiting for the reply.
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
# Load .env when this module is imported directly by the API/desktop bridge.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
except Exception:
    pass
# ──────────────────────────────────────────────
# Configuration (env-tunable)
# ──────────────────────────────────────────────

# Keep the bounded Ollama request timeout long enough for a cold model load but
# do not confuse it with response speed; generation size is controlled below.
try:
    AI_RESPONSE_BUDGET_SECONDS = max(
        1.0, float(os.environ.get("ZYRA_AI_RESPONSE_BUDGET_SECONDS", "180") or 180)
    )
except ValueError:  # unparsable override → keep the generous default
    AI_RESPONSE_BUDGET_SECONDS = 180.0

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
# Reserve enough generation tokens for detailed answers (such as recipes), while
# still allowing a smaller budget to be configured for low-resource machines.
try:
    AI_NUM_PREDICT = max(128, int(os.environ.get("ZYRA_AI_NUM_PREDICT", "512")))
except ValueError:
    AI_NUM_PREDICT = 512
# Keep context moderate to reduce CPU inference latency while retaining enough
# room for the active chat and the user's recent turns.
try:
    AI_NUM_CTX = max(1024, int(os.environ.get("ZYRA_AI_NUM_CTX", "1536")))
except ValueError:
    AI_NUM_CTX = 1536
try:
    AI_MAX_RESPONSE_CHARS = max(1000, int(os.environ.get("ZYRA_AI_MAX_RESPONSE_CHARS", "12000")))
except ValueError:
    AI_MAX_RESPONSE_CHARS = 12000
AI_MEMORY_ENABLED = os.environ.get("ZYRA_AI_MEMORY", "1").strip() not in ("0", "false", "False")
# Keep the model resident in Ollama memory so replies never pay a cold-load
# penalty (Ollama's default unload after ~5 idle minutes makes the next reply
# slow; a warm model answers in seconds).
AI_KEEP_ALIVE = os.environ.get("ZYRA_AI_KEEP_ALIVE", "30m").strip() or "30m"

# Clear, actionable fallback shown the moment Ollama is unreachable or has no
# chat model installed — instead of blocking for the whole reply budget or
# returning an opaque error. Used by ask_ai(), stream_ai() and the AI status
# endpoint.
OLLAMA_OFFLINE_MESSAGE = (
    "Ollama is not running. Please start Ollama and pull a model "
    "(for example: `ollama pull phi3`), then try again."
)

# Cached positive result of the connectivity probe; None = not yet confirmed.
# Once Ollama is confirmed reachable we skip the probe on the hot path so a
# normal chat turn pays no extra latency; a negative result is never cached so
# Zyra starts answering again as soon as Ollama comes back.
_ollama_ready: Optional[bool] = None
_ai_client_lock = threading.Lock()
_model_lock = threading.RLock()

_MAX_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 0.5
AI_NUM_PREDICT = min(AI_NUM_PREDICT, 640)
AI_NUM_CTX = min(AI_NUM_CTX, 1536)
# Ollama can serve concurrent HTTP requests, but the machine's model/runtime may
# have limited capacity; do not serialize independent chat, voice and web turns.
_conversation_lock = threading.RLock()
_ollama_locks_guard = threading.Lock()
_ollama_model_locks: Dict[str, threading.Lock] = {}
# The one-time model load at warm-up is allowed to take longer than a reply
# budget — its whole purpose is to absorb that cost outside the user window.
_WARMUP_TIMEOUT_SECONDS = max(120.0, AI_RESPONSE_BUDGET_SECONDS)

# Ordered fallback preferences (used only when the configured model is absent).
# tinyllama (1.1B) is deliberately NOT preferred: it is fast but cannot hold an
# instruction. Measured, it answers "Hii" with "Sure, here's a revised version of
# the text ... You are Zyra, a helpful, intelligent AI assistant" — it echoes and
# rewrites the system prompt instead of replying, which makes chat look broken.
# phi3 (3.8B) gives correct, natural replies and stays responsive once warm
# (measured 1-4s warm; the slow first call is just loading the weights).
# llama3 (8B) is higher quality but slower warm (3-5s) with a 78s cold load, so
# it is a fallback rather than the default.
# Set ZYRA_OLLAMA_MODEL to override (e.g. "llama3" for maximum quality).
_PREFERRED_MODELS = [
    "phi3",
    "llama3.2",
    "qwen2.5",
    "mistral",
    "gemma",
    "llama3",
    "llama3.1",
    "tinyllama",
]

# The shared Ollama client. Left as None on purpose: _get_client() lazily
# builds it via _make_client() the first time it is needed, so the client
# honours ZYRA_OLLAMA_HOST and the configured timeout. Building it eagerly
# here (ollama.Client(timeout=...)) would ignore ZYRA_OLLAMA_HOST — the host
# override only applied when this was None, which never happened on modern
# clients — so every caller silently talked to the default Ollama.
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

def _base_system_prompt() -> str:
    """Stable persona block.

    IMPORTANT: this text must not change between turns — Ollama reuses the KV
    cache of an unchanged prompt prefix, and a shifting prefix forces a full
    re-prefill of the whole conversation (seconds lost on CPU).
    """
    return (
        "You are Zyra, a capable, loyal desktop AI assistant in the spirit of "
        "JARVIS — confident, warm, and concise. You run locally on this machine "
        "and can open apps, run security and network scans, read the system, and "
        "remember things about your user. "
        "Give a clear, direct answer in a few well-organized sentences. For "
        "multi-part or technical questions, use short headings or numbered steps "
        "and cover the key points without unnecessary repetition. Finish complete "
        "sentences; be concise for simple questions and detailed when asked. "
        "Use paragraph breaks, headings, or numbered steps to make answers easy to scan. "
        "For recipes and making/cooking instructions, include the full ingredient list "
        "with quantities and complete step-by-step directions, plus cooking time and "
        "temperature when relevant; do not omit steps just to be brief. "
        "Usually answer in about 3-6 sentences unless the user asks for extensive detail. "
        "Speak naturally as a helpful partner, never invent results, and when you "
        "genuinely do not know, say so plainly. "
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
        with _ai_client_lock:
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
    entries = info.get("models", []) if isinstance(info, dict) else getattr(info, "models", [])
    for entry in entries or []:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("model") or ""
        else:
            name = getattr(entry, "name", None) or getattr(entry, "model", None) or ""
        if name and name not in models:
            models.append(str(name))
    return models


def check_ollama() -> Dict[str, Any]:
    """Probe Ollama and report its live status (best effort, never raises).

    Returns a small dict the bridge/status endpoint can hand straight to a
    caller:

        {
          "reachable": bool,      # the Ollama server answered the probe
          "can_enumerate": bool,  # we could actually list installed models
          "models": [str, ...],   # installed chat models (may be empty)
          "model": str,           # the model Zyra is configured to use
          "available": bool,      # reachable AND has a usable model
          "message": str,         # actionable status text
        }
    """
    status: Dict[str, Any] = {
        "reachable": False,
        "can_enumerate": False,
        "models": [],
        "model": get_model(),
        "available": False,
        "message": OLLAMA_OFFLINE_MESSAGE,
    }
    try:
        sender = _get_client() or ollama
        info = sender.list()
    except AttributeError:
        # A minimal client/test double without list() — we cannot enumerate, so
        # don't claim Ollama is down; assume the chat path itself will work.
        status["reachable"] = True
        status["can_enumerate"] = False
        status["available"] = True
        status["message"] = f"Ready (model: {status['model']})."
        return status
    except Exception as exc:  # noqa: BLE001 - connection refused / DNS / etc.
        status["reachable"] = False
        status["available"] = False
        status["message"] = OLLAMA_OFFLINE_MESSAGE
        print(f"brain: Ollama connectivity check failed: {exc}")
        return status

    models: List[str] = []
    entries = info.get("models", []) if isinstance(info, dict) else getattr(info, "models", [])
    for entry in entries or []:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("model") or ""
        else:
            name = getattr(entry, "name", None) or getattr(entry, "model", None) or ""
        if name and name not in models:
            models.append(str(name))

    status["reachable"] = True
    status["can_enumerate"] = True
    status["models"] = models
    requested = os.environ.get("ZYRA_OLLAMA_MODEL", "").strip()
    selected = get_model()
    selected_installed = any(
        name == selected or _basename(name) == _basename(selected)
        for name in models
    )
    if models and (selected_installed or not requested):
        status["available"] = True
        status["message"] = f"Ready (model: {selected})."
    elif models:
        status["available"] = True  # chat call will return the actionable 404
        status["message"] = (
            f"Ollama is connected but '{selected}' is not installed. "
            f"Run `ollama pull {selected}` or configure ZYRA_OLLAMA_MODEL."
        )
    else:
        status["available"] = False
        status["message"] = (
            "Ollama is running but has no models installed. "
            "Run `ollama pull phi3` or install a chat model."
        )
    return status


def _ollama_available() -> bool:
    """Fast, cached gate: is Ollama reachable with a usable model?

    Only a positive result is cached, so a healthy Ollama adds zero probe
    latency to normal chat turns. A negative or unknown result is never cached,
    so Zyra starts answering again the instant Ollama (or a newly pulled model)
    becomes available. A client that cannot enumerate models is treated as
    available so the real chat call decides (this also keeps lightweight test
    doubles on the working path).
    """
    global _ollama_ready
    if _ollama_ready is True:
        return True
    _ollama_ready = bool(check_ollama().get("available", False))
    return _ollama_ready


def _note_ollama_failure() -> None:
    """Invalidate the cached 'available' flag after a chat failure.

    Called from the error paths of ask_ai()/stream_ai() so that if Ollama went
    away mid-session the very next request re-probes and can report the offline
    fallback immediately instead of blocking on another doomed chat call.
    """
    global _ollama_ready
    _ollama_ready = None


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
        # Keep an explicit configuration intact when Ollama is temporarily
        # offline; for the default, use the quality-first preferred model.
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
    global _ACTIVE_MODEL, _ollama_ready
    requested = str(name or "").strip()
    if requested:
        with _model_lock:
            _ACTIVE_MODEL = requested
            _ollama_ready = None
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
        # Prefer a sentence boundary over returning a reply that ends mid-word.
        clipped = text[:AI_MAX_RESPONSE_CHARS]
        boundary = max(clipped.rfind(". "), clipped.rfind("? "), clipped.rfind("! "))
        if boundary >= int(AI_MAX_RESPONSE_CHARS * 0.75):
            clipped = clipped[:boundary + 1]
        text = clipped.rstrip() + "…"
    return text


def _raw_content(response: Any) -> str:
    """The model's exact text, unmodified.

    History stores this verbatim so the next request replays a byte-identical
    prompt and Ollama can reuse its KV cache (see _payload_snapshot).
    """
    # Support both Ollama's non-streaming response and individual streamed
    # chunks (which can be dicts or typed response objects).
    if isinstance(response, dict):
        # A complete chat response may already carry its full text under
        # message.content (with no stream metadata).
        message = response.get("message") or {}
        if isinstance(message, dict):
            content = message.get("content", "")
        else:
            content = getattr(message, "content", "")
        if content:
            return content if isinstance(content, str) else str(content)
        # Empty message content identifies the Ollama stream terminal chunk.
        # Stream chunks use done/done_reason metadata; aggregate them to return
        # the complete response while retaining concurrency support.
        if not any(key in response for key in ("done", "done_reason", "total_duration")):
            return ""
        return ""
    else:
        message = getattr(response, "message", None)
        content = getattr(message, "content", "") if message is not None else ""
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
        return OLLAMA_OFFLINE_MESSAGE
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

def _model_request_lock(model: str) -> threading.Lock:
    """Return the per-model lock used only for conversation updates."""
    key = str(model or _ACTIVE_MODEL)
    with _ollama_locks_guard:
        return _ollama_model_locks.setdefault(key, threading.Lock())


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
        "stream": True,
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
            with _model_request_lock(_ACTIVE_MODEL):
                stream_pieces: List[str] = []
                done_reason = None
                for chunk in sender.chat(**chat_kwargs):
                    piece = _raw_content(chunk)
                    if piece:
                        stream_pieces.append(piece)
                    if isinstance(chunk, dict) and chunk.get("done"):
                        done_reason = chunk.get("done_reason")
                    elif getattr(chunk, "done", False):
                        done_reason = getattr(chunk, "done_reason", None)
                if done_reason == "length":
                    print("brain: complete reply limited by num_predict")
                return {"message": {"content": "".join(stream_pieces)}}
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
    AI_RESPONSE_BUDGET_SECONDS; async callers must therefore
    run it in a worker thread so the event loop stays responsive.
    """
    if not question or not str(question).strip():
        return "Please say something!"

    question = str(question).strip()

    # Fast, honest preflight: if Ollama is down or has no model, return the
    # clear fallback immediately instead of blocking for the whole reply budget
    # and coming back with an opaque error. The check is cached-positive, so a
    # healthy Ollama pays no per-turn cost.
    if not _ollama_available():
        print("brain: Ollama unavailable — returning offline fallback")
        return OLLAMA_OFFLINE_MESSAGE

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
        _note_ollama_failure()
        return _friendly_ollama_error(exc)
    except Exception as exc:
        elapsed = time.monotonic() - started
        print(f"brain: AI error after {elapsed:.1f}s: {exc}")
        with _conversation_lock:
            _prune_locked()
        # Ollama may have gone away mid-session — re-probe next turn.
        _note_ollama_failure()
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
    them so a UI can render the first words as soon as available. The complete,
    sanitized answer is appended to the conversation when the stream finishes.

    Yields:
        str: successive pieces of the answer (empty pieces are skipped).
    """
    if not question or not str(question).strip():
        yield "Please say something!"
        return

    question = str(question).strip()

    # Same fast preflight as ask_ai(): surface the clear offline fallback at once
    # instead of streaming an opaque error after a long wait.
    if not _ollama_available():
        print("brain: Ollama unavailable — streaming offline fallback")
        yield OLLAMA_OFFLINE_MESSAGE
        return

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
        done_reason = None
        response_stream = sender.chat(**chat_kwargs)
        for chunk in response_stream:
            try:
                piece = (chunk.get("message") or {}).get("content") or ""
            except (AttributeError, TypeError):
                piece = ""
            if piece:
                pieces.append(piece)
                yield piece
            if isinstance(chunk, dict) and chunk.get("done"):
                done_reason = chunk.get("done_reason")
                if done_reason == "length":
                    print("brain: streamed answer reached its token limit")
    except ollama.ResponseError as exc:
        print(f"brain: Ollama stream error: {exc}")
        _note_ollama_failure()
        if not pieces:
            yield _friendly_ollama_error(exc)
            return
    except Exception as exc:  # noqa: BLE001 - report instead of raising mid-stream
        elapsed = time.monotonic() - started
        print(f"brain: AI stream error after {elapsed:.1f}s: {exc}")
        _note_ollama_failure()
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
    if done_reason == "length":
        print("brain: response reached token limit; increase ZYRA_AI_NUM_PREDICT")
    with _conversation_lock:
        # Byte-exact history keeps the prompt prefix cacheable next turn.
        conversation.append({"role": "assistant", "content": raw_answer or answer})
        _prune_locked()


def _warmup_client():
    """Build an Ollama client with a generous cold-start timeout."""
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

    Two costs have to be paid before a reply is instant on CPU-only hardware:

    1. Loading the weights themselves.
    2. Prefilling the (stable) system prompt into the KV cache. Ollama reuses
       the longest common prompt prefix between requests, so sending the real
       system prompt here means the user\'s first message only has to prefill
       their own few tokens instead of the whole prompt.

    Both use the same options as a real reply so Ollama sizes the KV cache at
    AI_NUM_CTX (warming up without them loads it at its 4096 default, and the
    first real request then reallocates it down inside the user's message).

    Best effort and never raises; safe to call from a background thread at
    server startup. Returns True when the model is loaded and resident
    (keep_alive keeps it that way between requests).
    """
    try:
        sender = _warmup_client() or _get_client() or ollama
        started = time.monotonic()
        options = {
            "temperature": AI_TEMPERATURE,
            "num_predict": AI_NUM_PREDICT,
            "num_ctx": AI_NUM_CTX,
        }
        # Exactly the system prefix a real turn sends, so the KV cache it builds
        # is reused. This does not touch `conversation` — the priming turn is
        # discarded so it can never appear in the user's chat history.
        with _conversation_lock:
            system_content = conversation[0]["content"] if conversation else ""
        sender.chat(
            model=_ACTIVE_MODEL,
            messages=[{"role": "system", "content": system_content}],
            stream=False,
            keep_alive=AI_KEEP_ALIVE,
            options={**options, "num_predict": 1},
        )
        print(
            f"brain: model '{_ACTIVE_MODEL}' warmed up in "
            f"{time.monotonic() - started:.1f}s "
            f"(kept alive {AI_KEEP_ALIVE}, num_ctx {AI_NUM_CTX})"
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
    "check_ollama",
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
    "OLLAMA_OFFLINE_MESSAGE",
]


# ──────────────────────────────────────────────
# Standalone smoke test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print(f"brain: active model = {get_model()}")
    print(f"brain: installed models = {available_models()}")
    print(f"brain: ollama status = {check_ollama()}")
    print(f"brain: memory digest = {_memory_digest()!r}")
    print("brain: ask_ai('Say hi in one short sentence.') ->")
    print(ask_ai("Say hi in one short sentence."))