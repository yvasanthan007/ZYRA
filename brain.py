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
    history depth, timeouts and the response-length cap are all tunable:
      ZYRA_OLLAMA_MODEL, ZYRA_OLLAMA_HOST, ZYRA_AI_TEMPERATURE,
      ZYRA_AI_NUM_PREDICT, ZYRA_AI_MAX_HISTORY, ZYRA_AI_TIMEOUT_SECONDS,
      ZYRA_AI_MAX_RESPONSE_CHARS, ZYRA_AI_MEMORY (0 disables memory injection),
      ZYRA_AI_FIRST_TOKEN_TIMEOUT, ZYRA_AI_STREAM_STALL, ZYRA_AI_KEEP_ALIVE
  • Streaming sentence generation — ask_ai_stream() yields complete sentences
    while the model is still generating, so speech starts on the first
    sentence instead of waiting for the whole answer. Normal generation time is
    never treated as an error (no artificial "10 second budget"); only a dead
    backend or a stalled stream is reported, and then gracefully.
  • Request sessions — every request gets a session id, and only the newest
    session may finish: a superseded answer can never be appended to the
    conversation or spoken after a newer request.
  • Model stays warm (keep_alive) so no reply pays a cold-load penalty.
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
import queue
import re
import threading
import time
from typing import Any, Dict, List, Optional

import ollama

# ── Windows console safety ──────────────────────────────────────────────
# Force UTF-8 output so status prints never crash with UnicodeEncodeError on a
# cp1252 console (same guard used by main.py / start_zyra.py).
import sys as _sys

for _stream in (_sys.stdout, _sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ──────────────────────────────────────────────
# Configuration (env-tunable)
# ──────────────────────────────────────────────

# ── Latency model ───────────────────────────────────────────────────────────
# ZYRA no longer aborts a normal reply on a wall-clock "budget". Generation is
# streamed and spoken sentence-by-sentence as it arrives, so a slow (CPU) model
# is heard as it produces text instead of being reported as an error after 10
# seconds. Two watchdogs remain and both fire only on a genuinely broken
# backend:
#   • no FIRST token at all within AI_FIRST_TOKEN_TIMEOUT_SECONDS
#   • the stream stalls for AI_STREAM_STALL_SECONDS between tokens
# AI_MAX_REPLY_SECONDS is only a runaway-generation guard.
AI_FIRST_TOKEN_TIMEOUT_SECONDS = float(os.environ.get("ZYRA_AI_FIRST_TOKEN_TIMEOUT", "90"))
AI_STREAM_STALL_SECONDS = float(os.environ.get("ZYRA_AI_STREAM_STALL", "90"))
AI_MAX_REPLY_SECONDS = float(os.environ.get("ZYRA_AI_MAX_REPLY_SECONDS", "300"))

# HTTP timeout for the Ollama connection itself (an open stream keeps it alive,
# so this only guards a dead socket, never normal generation).
AI_TIMEOUT_SECONDS = float(
    os.environ.get("ZYRA_AI_TIMEOUT_SECONDS", "").strip() or AI_MAX_REPLY_SECONDS
)
MAX_HISTORY = int(os.environ.get("ZYRA_AI_MAX_HISTORY", "8"))
# Cap a single historical message so a long past answer cannot flood the
# context window on every following request.
HISTORY_MESSAGE_CHARS = int(os.environ.get("ZYRA_AI_HISTORY_CHARS", "600"))
AI_TEMPERATURE = float(os.environ.get("ZYRA_AI_TEMPERATURE", "0.4"))
# Conversational answers: enough room for a complete thought, short enough to
# stay natural when spoken aloud ("avoid unnecessarily long answers").
AI_NUM_PREDICT = int(os.environ.get("ZYRA_AI_NUM_PREDICT", "220"))
AI_MAX_RESPONSE_CHARS = int(os.environ.get("ZYRA_AI_MAX_RESPONSE_CHARS", "3000"))
# Longest clause handed to TTS before a natural break is forced — keeps speech
# responsive instead of waiting for a comma-less paragraph to finish.
AI_MAX_SENTENCE_CHARS = int(os.environ.get("ZYRA_AI_MAX_SENTENCE_CHARS", "240"))
AI_MEMORY_ENABLED = os.environ.get("ZYRA_AI_MEMORY", "1").strip() not in ("0", "false", "False")
# Keep the model resident in Ollama memory so replies never pay a cold-load
# penalty (Ollama's default unload after ~5 idle minutes makes the next reply
# slow; a warm model answers in seconds).
AI_KEEP_ALIVE = os.environ.get("ZYRA_AI_KEEP_ALIVE", "30m").strip() or "30m"

_MAX_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 0.5
# The one-time model load at warm-up absorbs the cold-start cost, off the
# user's clock.
_WARMUP_TIMEOUT_SECONDS = 300.0

# Ordered fallback preferences (used only when the configured model is absent).
# Small, fast models come first so a voice turn stays conversational on typical
# hardware.
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
    """ZYRA's spoken persona — calm, concise, expert, never robotic.

    Original characterisation: composed and slightly formal like a professional
    aide, but warm and natural. Written for speech, so formatting is banned.
    """
    return (
        "You are ZYRA, a calm, intelligent voice assistant. You speak like a "
        "composed human expert: concise, confident, natural, slightly formal, "
        "never robotic and never over-enthusiastic. Answer the user's question "
        "directly and accurately. Keep casual and simple questions to one or "
        "two short sentences; for technical questions give the key facts first "
        "and add only the detail that genuinely helps. Vary your wording "
        "naturally instead of repeating the same opening every time. Never "
        "mention being an AI language model, never use filler or flattery, "
        "never repeat the question back. Your text is spoken aloud, so never "
        "output markdown, bullet points, code blocks, emoji, file paths or "
        "logs. "
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
    """Keep the system slot plus the N most recent messages.

    Long historical messages are also truncated, so one verbose answer can
    never bloat every following request (small prompt = low latency).
    """
    for message in conversation[1:]:
        content = message.get("content")
        if isinstance(content, str) and len(content) > HISTORY_MESSAGE_CHARS:
            message["content"] = content[:HISTORY_MESSAGE_CHARS].rstrip() + "…"
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


def _looks_like_connection_error(exc: BaseException) -> bool:
    """True for 'Ollama is not running / not reachable' style failures."""
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    return any(
        marker in text or marker in name
        for marker in ("connect", "refused", "unreachable", "no route", "timed out", "timeout")
    )


def _friendly_error(exc: BaseException) -> str:
    """Turn a technical failure into a short, natural ZYRA sentence.

    Internal errors are logged, never spoken: the user hears one calm,
    actionable line and nothing about "brain:", budgets or stack traces.
    """
    status = getattr(exc, "status_code", None)
    model = get_model()
    if status == 404:
        return (
            f"I couldn't find the {model} model in Ollama. "
            f"Install it with ollama pull {model}, then ask me again."
        )
    lowered = str(exc).lower()
    if _looks_like_connection_error(exc) or "connection" in lowered or "refused" in lowered:
        return (
            "I can't reach the local language model right now. "
            "Please make sure Ollama is running, then ask me again."
        )
    if "load" in lowered or "unavailable" in lowered:
        return "The model is still loading. Give me a moment and ask me again."
    return "Something went wrong while I was thinking. Please ask me again."


# Backwards-compatible alias (older callers imported this name).
_friendly_ollama_error = _friendly_error


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


# ──────────────────────────────────────────────
# Request sessions (a stale answer can never be spoken)
# ──────────────────────────────────────────────

_request_lock = threading.Lock()
_session_counter = 0
_latest_session = 0


def begin_request_session() -> int:
    """Start a new AI request session; any older request becomes stale."""
    global _session_counter, _latest_session
    with _request_lock:
        _session_counter += 1
        _latest_session = _session_counter
        return _session_counter


def current_request_session() -> int:
    """Id of the newest request session."""
    with _request_lock:
        return _latest_session


def is_current_session(session_id: Optional[int]) -> bool:
    """False when a newer request has superseded ``session_id``."""
    if session_id is None:
        return True
    with _request_lock:
        return session_id == _latest_session


def cancel_current_request() -> int:
    """Invalidate the in-flight request (barge-in) so it stops producing text."""
    return begin_request_session()


# ──────────────────────────────────────────────
# Streaming chat runner (watchdogs, retry, cancellation)
# ──────────────────────────────────────────────

def _iter_model_chunks(
    messages: List[Dict[str, str]],
    session_id: Optional[int],
    first_token_timeout: float = AI_FIRST_TOKEN_TIMEOUT_SECONDS,
    stall_timeout: float = AI_STREAM_STALL_SECONDS,
):
    """Yield content pieces from Ollama's streaming chat.

    Only genuine failures end this generator: nothing at all within
    ``first_token_timeout`` (backend dead / model never loaded) or a stall
    mid-answer. Normal generation time is never treated as an error.
    """
    deadline = time.monotonic() + AI_MAX_REPLY_SECONDS
    last_exc: Optional[BaseException] = None

    for attempt in range(_MAX_ATTEMPTS):
        if not is_current_session(session_id):
            return

        sender = _get_client() or ollama
        chat_kwargs: Dict[str, Any] = {
            "model": _ACTIVE_MODEL,
            "messages": messages,
            "keep_alive": AI_KEEP_ALIVE,
            "stream": True,
            "options": {
                "temperature": AI_TEMPERATURE,
                "num_predict": AI_NUM_PREDICT,
            },
        }
        q: "queue.Queue" = queue.Queue()
        stop = threading.Event()

        def _reader(chat_kwargs=chat_kwargs, q=q, stop=stop) -> None:
            """Read the Ollama stream in a daemon thread so watchdogs work."""
            stream = None
            try:
                stream = sender.chat(**chat_kwargs)
                for chunk in stream:
                    if stop.is_set():
                        break
                    try:
                        piece = chunk["message"]["content"]
                    except (KeyError, TypeError, AttributeError):
                        piece = ""
                    if piece:
                        q.put(("chunk", piece))
                q.put(("done", None))
            except BaseException as exc:  # noqa: BLE001 - relayed to the caller
                q.put(("error", exc))
            finally:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass

        threading.Thread(
            target=_reader, name="zyra-ollama-stream", daemon=True
        ).start()

        first = True
        produced_any = False
        retry = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stop.set()
                raise TimeoutError("reply exceeded the maximum length cap")
            wait = min(first_token_timeout if first else stall_timeout, remaining)
            try:
                kind, payload = q.get(timeout=wait)
            except queue.Empty:
                stop.set()
                if first:
                    last_exc = TimeoutError("no response from the model")
                    retry = True                   # one retry, then give up
                    break
                # The answer had already started: end it quietly with what we
                # have rather than discarding text the user never heard.
                print("brain: stream stalled — ending the reply early")
                return

            if kind == "chunk":
                first = False
                produced_any = True
                if not is_current_session(session_id):
                    stop.set()
                    return                          # superseded → stop talking
                yield payload
                continue

            if kind == "done":
                return

            # kind == "error": one retry, otherwise a real failure.
            exc = payload
            status = getattr(exc, "status_code", None)
            if not produced_any and attempt + 1 < _MAX_ATTEMPTS:
                if status == 404 and _reselect_missing_model(chat_kwargs):
                    retry = True
                elif status in (429, 500, 503):
                    retry = True
                elif _looks_like_connection_error(exc):
                    retry = True
            if retry:
                last_exc = exc
                break
            if produced_any:
                print(f"brain: stream error after a partial reply ({exc})")
                return
            raise exc

        if not retry:
            return
        time.sleep(_RETRY_DELAY_SECONDS)      # one retry, never a retry loop

    if last_exc is not None:
        raise last_exc
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[,;:])\s+")


def iter_sentences(pieces, max_chars: int = AI_MAX_SENTENCE_CHARS):
    """Buffer streamed text and yield complete, speakable sentences.

    A sentence is released the moment its terminating punctuation arrives, so
    speech starts on sentence one while the model is still writing sentence
    two. A long clause without punctuation is released at a natural comma or at
    ``max_chars``, so speech never waits for a whole paragraph.
    """
    buffer = ""
    for piece in pieces:
        buffer += piece
        while True:
            match = _SENTENCE_SPLIT_RE.search(buffer)
            if not match:
                break
            sentence = buffer[:match.end()].strip()
            buffer = buffer[match.end():]
            if sentence:
                yield sentence

        if len(buffer) >= max_chars:
            cut = buffer.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            emit = buffer[:cut].strip()
            buffer = buffer[cut:].lstrip()
            if emit:
                yield emit
        elif len(buffer) >= max_chars // 2:
            match = _CLAUSE_SPLIT_RE.search(buffer)
            if match and match.end() >= max_chars // 2:
                emit = buffer[:match.end()].strip()
                buffer = buffer[match.end():]
                if emit:
                    yield emit

    tail = buffer.strip()
    if tail:
        yield tail


def _drop_user_turn_locked(question: str) -> None:
    """Remove the orphaned user turn of a superseded request."""
    for index in range(len(conversation) - 1, 0, -1):
        message = conversation[index]
        if message.get("role") == "user" and message.get("content") == question:
            del conversation[index]
            return


# ──────────────────────────────────────────────
# Public entry points
# ──────────────────────────────────────────────

def ask_ai_stream(question, session_id: Optional[int] = None):
    """Stream ZYRA's answer as complete sentences.

    The first sentence is yielded as soon as the model finishes it, so speech
    can start while the rest of the answer is still being generated. The full
    answer is appended to the conversation history exactly once, and only when
    this request is still the newest one (a superseded reply is dropped).

    Yields:
        str — one speakable sentence at a time.
    """
    if not question or not str(question).strip():
        yield "Please say something!"
        return

    question = str(question).strip()
    if session_id is None:
        session_id = begin_request_session()

    system_text = _build_system_prompt(_memory_digest(), datetime.datetime.now())
    with _conversation_lock:
        _refresh_system_locked(system_text)
        conversation.append({"role": "user", "content": question})
        _prune_locked()
        # Snapshot: the in-flight request must never see the shared
        # conversation mutate under it mid-generation.
        snapshot = [dict(m) for m in conversation]

    started = time.monotonic()
    sentences: List[str] = []
    error_text = ""
    try:
        for sentence in iter_sentences(_iter_model_chunks(snapshot, session_id)):
            if not is_current_session(session_id):
                print("brain: request superseded — withholding the stale reply")
                break
            sentences.append(sentence)
            yield sentence
        if not sentences and is_current_session(session_id):
            # The stream closed without producing anything: answer with one
            # calm line instead of leaving the user in silence.
            error_text = "I didn't get a response from the model that time. Please ask me again."
            yield error_text
    except Exception as exc:  # noqa: BLE001 - never leak a raw error to TTS
        print(f"brain: AI request failed ({type(exc).__name__}: {exc})")
        if not sentences:
            error_text = _friendly_error(exc)
            yield error_text
    finally:
        with _conversation_lock:
            if not is_current_session(session_id):
                # A newer request replaced this one: drop this orphaned turn.
                if not sentences:
                    _drop_user_turn_locked(question)
            elif sentences:
                answer = _sanitize_answer(" ".join(sentences))
                if answer:
                    conversation.append({"role": "assistant", "content": answer})
            _prune_locked()

        if sentences:
            print(
                f"brain: reply in {time.monotonic() - started:.2f}s "
                f"({len(' '.join(sentences))} chars, {len(sentences)} sentence(s), "
                f"model={get_model()})"
            )
        elif error_text:
            print(f"brain: no reply produced after {time.monotonic() - started:.2f}s")


def ask_ai(question) -> str:
    """Ask the AI a question and return the complete answer (blocking).

    Backwards-compatible wrapper over :func:`ask_ai_stream`. The voice pipeline
    uses the streaming form so speech starts on the first sentence; the chat UI
    and API bridges keep using this one.
    """
    return " ".join(part for part in ask_ai_stream(question) if part).strip()


# ──────────────────────────────────────────────
# Model warm-up (removes the cold-start penalty)
# ──────────────────────────────────────────────

def _warmup_client():
    """A dedicated client with a generous timeout for the one-time model load.

    The normal client guards a dead socket; warm-up exists precisely to pay the
    cold model-load cost up front, off the user's clock.
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
    "ask_ai_stream",
    "iter_sentences",
    "begin_request_session",
    "current_request_session",
    "is_current_session",
    "cancel_current_request",
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
    "AI_KEEP_ALIVE",
    "AI_NUM_PREDICT",
    "AI_MAX_REPLY_SECONDS",
    "AI_FIRST_TOKEN_TIMEOUT_SECONDS",
    "AI_STREAM_STALL_SECONDS",
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