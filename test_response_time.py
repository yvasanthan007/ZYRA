"""
test_response_time.py — ZYRA AI latency / streaming regression tests.

The old design forced every reply into a hard 10-second "budget" and reported a
timed-out reply as an error. The streaming design must instead:

  • start speaking on the FIRST complete sentence (no wait for the whole reply),
  • never treat normal generation time as an error,
  • record the answer in the conversation exactly once,
  • report only GENUINE backend failures, in a friendly spoken form,
  • keep the model warm and make superseded replies un-speakable.

These tests run fully offline by stubbing the Ollama client.
"""
import time
import unittest
from unittest import mock

import brain


class _FakeStreamClient:
    """Stand-in for the ollama client's streaming chat()."""

    def __init__(self, chunks=(), delay=0.0, exc=None):
        self.chunks = list(chunks)
        self.delay = delay
        self.exc = exc
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc

        def _stream():
            for chunk in self.chunks:
                if self.delay:
                    time.sleep(self.delay)
                yield {"message": {"content": chunk}}

        return _stream()


class StreamingReplyTests(unittest.TestCase):
    def setUp(self):
        brain.clear_conversation()

    def tearDown(self):
        brain.clear_conversation()

    def test_no_artificial_reply_budget_remains(self):
        # The 10-second wall-clock failure mode must be gone entirely.
        self.assertFalse(hasattr(brain, "AI_RESPONSE_BUDGET_SECONDS"))
        self.assertGreaterEqual(brain.AI_FIRST_TOKEN_TIMEOUT_SECONDS, 30.0)
        self.assertGreaterEqual(brain.AI_MAX_REPLY_SECONDS, 60.0)
        # A single HTTP connection timeout may not act as a short reply budget.
        self.assertGreater(brain.AI_TIMEOUT_SECONDS, 30.0)

    def test_first_sentence_streams_before_the_reply_finishes(self):
        fake = _FakeStreamClient(
            ["Ethical hacking is authorized security testing. ",
             "It happens with permission. ",
             "It finds weaknesses before attackers do."],
            delay=0.05,
        )
        seen = []
        with mock.patch.object(brain, "_get_client", return_value=fake):
            for sentence in brain.ask_ai_stream("what is ethical hacking?"):
                seen.append((time.monotonic(), sentence))
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen[0][1],
                         "Ethical hacking is authorized security testing.")
        self.assertLess(seen[0][0], seen[-1][0])

    def test_generation_time_is_not_an_error(self):
        # 6 chunks x 0.15 s beats any old "budget" style cap; the complete
        # answer must still come back untouched.
        chunks = [f"Part {i}. " for i in range(6)]
        fake = _FakeStreamClient(chunks, delay=0.15)
        with mock.patch.object(brain, "_get_client", return_value=fake):
            answer = brain.ask_ai("tell me something")
        for i in range(6):
            self.assertIn(f"Part {i}.", answer)
        self.assertNotIn("budget", answer.lower())
        self.assertNotIn("timed out", answer.lower())

    def test_answer_is_recorded_in_history_exactly_once(self):
        fake = _FakeStreamClient(["One sentence. ", "And another."])
        with mock.patch.object(brain, "_get_client", return_value=fake):
            brain.ask_ai("hello")
        assistants = [m for m in brain.get_conversation() if m["role"] == "assistant"]
        self.assertEqual(len(assistants), 1)
        self.assertEqual(assistants[0]["content"], "One sentence. And another.")

    def test_keep_alive_and_streaming_are_requested(self):
        fake = _FakeStreamClient(["Hi."])
        with mock.patch.object(brain, "_get_client", return_value=fake):
            brain.ask_ai("hello")
        kwargs = fake.calls[0]
        self.assertTrue(kwargs.get("stream"))
        self.assertEqual(kwargs.get("keep_alive"), brain.AI_KEEP_ALIVE)
        self.assertEqual(kwargs.get("model"), brain.get_model())


    def test_connection_failure_is_reported_friendly_and_once(self):
        fake = _FakeStreamClient(exc=ConnectionError("connection refused"))
        with mock.patch.object(brain, "_get_client", return_value=fake):
            started = time.monotonic()
            answer = brain.ask_ai("hello")
            elapsed = time.monotonic() - started
        # One retry only — never an endless retry loop.
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("Ollama", answer)
        self.assertNotIn("brain:", answer)
        self.assertNotIn("Traceback", answer)
        self.assertLess(elapsed, 10.0)

    def test_stale_reply_is_withheld_and_not_recorded(self):
        fake = _FakeStreamClient(
            ["First sentence. ", "Second sentence. ", "Third sentence."],
            delay=0.02,
        )
        with mock.patch.object(brain, "_get_client", return_value=fake):
            session = brain.begin_request_session()
            stream = brain.ask_ai_stream("first question", session_id=session)
            first = next(stream)
            self.assertEqual(first, "First sentence.")
            brain.begin_request_session()          # a newer request took over
            rest = list(stream)
        self.assertEqual(rest, [])                 # nothing stale was spoken
        self.assertEqual(
            [m for m in brain.get_conversation() if m["role"] == "assistant"], []
        )

    def test_empty_question_answers_instantly(self):
        started = time.monotonic()
        self.assertEqual(brain.ask_ai("   "), "Please say something!")
        self.assertLess(time.monotonic() - started, 1.0)

    def test_no_response_at_all_is_reported_without_hanging(self):
        # The backend accepts the call but never produces a token: the watchdog
        # must end the reply with a friendly message (never a raw timeout).
        fake = _FakeStreamClient(chunks=(), delay=0.0)
        with mock.patch.object(brain, "AI_FIRST_TOKEN_TIMEOUT_SECONDS", 0.3), \
             mock.patch.object(brain, "_get_client", return_value=fake):
            started = time.monotonic()
            answer = brain.ask_ai("hello")
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 6.0)
        self.assertTrue(answer.strip())
        self.assertNotIn("Traceback", answer)
        self.assertNotIn("reply budget", answer.lower())


if __name__ == "__main__":
    unittest.main()
