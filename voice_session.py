"""
voice_session.py — ZYRA ChatGPT-style continuous voice session state machine.

Implements a clean, thread-safe state machine that the main voice loop, the
backend bridge and the renderer UI all drive:

    IDLE -> LISTENING -> PROCESSING -> SPEAKING -> LISTENING -> ...

Design rules:
  * Only ONE voice session can be active at a time (module lock).
  * Microphone capture, STT, TTS and AI generation are all owned by a single
    active turn; nothing runs in the background after stop_voice() unless it
    is daemonized and explicitly released on shutdown.
  * After ZYRA finishes speaking the session returns to LISTENING automatically
    (continuous conversation). The user does NOT need to press the mic button
    between sentences.
  * Listening during speech is allowed (barge-in): the user can interrupt a
    speaking response and a fresh turn takes over immediately.
  * All state transitions and the captured turn counter are published atomically
    so the renderer never races the backend.
"""

import threading
import time
from enum import Enum, auto
from typing import Callable, Optional


class VoiceSessionState(Enum):
    """The ChatGPT-style voice session states."""
    IDLE = auto()        # Not listening, button shows "Start Voice"
    LISTENING = auto()   # Capturing audio, waiting for speech
    PROCESSING = auto()  # STT -> AI in flight (not yet speaking)
    SPEAKING = auto()    # TTS audio playing (or queued but sounding)
    ERROR = auto()       # Transient failure, recoverable by restart
    STOPPING = auto()    # Stopping in progress (cleanup)


class VoiceSession:
    """A single continuous voice session. One instance per app lifecycle."""

    def __init__(self):
        self._lock = threading.RLock()

        # --- State machine ---
        self.state = VoiceSessionState.IDLE
        self.next_state: Optional[VoiceSessionState] = None

        # --- Turn identity (mirrors main.py's turn/session counters) ---
        self.turn = 0
        self.session_id: Optional[str] = None

        # --- Prevent duplicate sessions / auto-stop timers ---
        self._stop_timer: Optional[threading.Timer] = None

        # --- Callbacks published to the UI (thread-safe) ---
        self._subscribers: list[Callable[[VoiceSessionState, VoiceSessionState], None]] = []

        # --- Operational flags ---
        self.running = False
        self.error_message: Optional[str] = None
        self.last_transcript: Optional[str] = None
        self.last_response: Optional[str] = None
        self.last_start_time = 0.0

        # --- Microphone / device selection (persisted) ---
        self.mic_device_index: Optional[int] = None
        self.mic_device_name: Optional[str] = None

    # --- Thread-safe state transitions ---
    def _set_state(self, new_state: VoiceSessionState) -> None:
        """Atomically move the state machine and notify subscribers."""
        with self._lock:
            old_state = self.state
            self.state = new_state
            self.next_state = None
            self._publish(old_state, new_state)

    def _publish(self, old_state: VoiceSessionState, new_state: VoiceSessionState) -> None:
        for cb in list(self._subscribers):
            try:
                cb(old_state, new_state)
            except Exception:
                # A subscriber must never break the session
                continue

    # --- Convenience getters ---
    def is_idle(self) -> bool:
        return self.state is VoiceSessionState.IDLE

    def is_listening(self) -> bool:
        return self.state is VoiceSessionState.LISTENING

    def is_processing(self) -> bool:
        return self.state is VoiceSessionState.PROCESSING

    def is_speaking(self) -> bool:
        return self.state is VoiceSessionState.SPEAKING

    def is_error(self) -> bool:
        return self.state is VoiceSessionState.ERROR

    def is_stopping(self) -> bool:
        return self.state is VoiceSessionState.STOPPING

    def is_active(self) -> bool:
        """True while a session is running (LISTENING, PROCESSING or SPEAKING).

        IDLE, ERROR and STOPPING are *not* active, so ``start()`` may begin a
        fresh session from any of them.
        """
        return self.state in (
            VoiceSessionState.LISTENING,
            VoiceSessionState.PROCESSING,
            VoiceSessionState.SPEAKING,
        )


    # --- Public API ---
    def start(self, on_state_change: Optional[Callable[[VoiceSessionState, VoiceSessionState], None]] = None) -> bool:
        """Begin a voice session. Returns False if already active."""
        with self._lock:
            if self.is_active():
                return False

            self.running = True
            self.state = VoiceSessionState.IDLE
            self._subscribers.append(on_state_change)

        self._set_state(VoiceSessionState.LISTENING)
        return True

    def stop(self) -> None:
        """Stop the session completely: release mic, cancel AI, stop TTS."""
        with self._lock:
            if self.state is VoiceSessionState.STOPPING:
                return
            self.state = VoiceSessionState.STOPPING

        # Cancel any pending auto-stop timer
        if self._stop_timer is not None:
            self._stop_timer.cancel()
            self._stop_timer = None

        # Transition to STOPPING while holding the lock briefly so a race with
        # start() cannot resurrect the session.
        with self._lock:
            self.running = False
            old = self.state
            self.state = VoiceSessionState.IDLE
            self._publish(old, self.state)

        # External cleanup of mic / TTS / AI is performed by the caller (see
        # voice_session_cleanup in main.py). We deliberately avoid touching the
        # audio stack here so this module stays UI/state-only.

    def cancel(self) -> None:
        """Cancel the current in-flight answer (interrupt)."""
        self._set_state(VoiceSessionState.IDLE)

    def has_error(self, message: str) -> None:
        """Record a transient error and surface it to the UI."""
        with self._lock:
            self.error_message = message
        self._set_state(VoiceSessionState.ERROR)

    def clear_error(self) -> None:
        with self._lock:
            self.error_message = None
        # Return from ERROR back to the last sane state
        self._set_state(VoiceSessionState.IDLE)

    def request_stop(self) -> None:
        """Request a quiet stop (e.g. while speaking)."""
        self._set_state(VoiceSessionState.STOPPING)


# ──────────────────────────────────────────────
# Module singleton + module-level convenience API
# ──────────────────────────────────────────────
#
# main.py imports ``session`` as a *function* returning the one process-wide
# VoiceSession (``session().state = ...``), plus a handful of thin wrappers so
# callers never have to touch the class directly. The instance is created
# lazily so importing this module has no side effects.

_session: Optional[VoiceSession] = None
_session_lock = threading.Lock()


def session() -> VoiceSession:
    """Return the single process-wide VoiceSession (created on first use)."""
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = VoiceSession()
    return _session


def get_state() -> VoiceSessionState:
    """Current state of the active session."""
    return session().state


def get_state_name() -> str:
    """Name of the current state (e.g. "LISTENING")."""
    return session().state.name


def is_listening() -> bool:
    return session().is_listening()


def is_speaking() -> bool:
    """True when the *state machine* is in SPEAKING.

    Note: this reflects the session state machine, not the audio device. For
    barge-in decisions that need to know whether audio is actually playing,
    use ``speak.is_speaking`` instead.
    """
    return session().is_speaking()


def is_idle() -> bool:
    return session().is_idle()


def is_error() -> bool:
    return session().is_error()


def is_active() -> bool:
    return session().is_active()


def get_last_transcript() -> Optional[str]:
    return session().last_transcript


def get_last_response() -> Optional[str]:
    return session().last_response


__all__ = [
    "VoiceSessionState",
    "VoiceSession",
    "session",
    "get_state",
    "get_state_name",
    "is_listening",
    "is_speaking",
    "is_idle",
    "is_error",
    "is_active",
    "get_last_transcript",
    "get_last_response",
]


