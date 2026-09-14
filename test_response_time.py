"""
test_response_time.py — Regression tests for ZYRA's guaranteed reply window.

brain.ask_ai must return within AI_RESPONSE_BUDGET_SECONDS (default 10s) even
when the model backend is slow or hangs: the HTTP timeout is capped by the
budget, the retry policy is deadline-aware (no retry once the window is spent),
and timeouts fall back to a fast, honest message. These tests run fully
offline by stubbing the Ollama client.
"""
import time
import unittest
from unittest import mock

import brain


class _FakeClient:
    """Minimal stand-in for the ollama client used by brain._run_chat."""

    def __init__(self, behaviour):
        self.behaviour = behaviour  # callable(**chat_kwargs) -> response/raise
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.behaviour(**kwargs)


class ResponseTimeBudgetTests(unittest.TestCase):
    def setUp(self):
        brain.clear_conversation()

    def tearDown(self):
        brain.clear_conversation()

    def test_default_budget_is_within_10_seconds(self):
        self.assertLessEqual(brain.AI_RESPONSE_BUDGET_SECONDS, 10.0)
        # The HTTP timeout can never exceed the reply budget.
        self.assertLessEqual(brain.AI_TIMEOUT_SECONDS, brain.AI_RESPONSE_BUDGET_SECONDS)
        # Generation is capped so answers finish inside the window.
        self.assertLessEqual(brain.AI_NUM_PREDICT, 150)

    def test_fast_backend_returns_answer_and_passes_keep_alive(self):
        fake = _FakeClient(lambda **kw: {"message": {"content": "Hi there!"}})
        with mock.patch.object(brain, "_get_client", return_value=fake):
            started = time.monotonic()
            answer = brain.ask_ai("hello")
            elapsed = time.monotonic() - started
        self.assertEqual(answer, "Hi there!")
        self.assertLess(elapsed, brain.AI_RESPONSE_BUDGET_SECONDS)
        # The model must be requested with keep_alive so it stays warm.
        self.assertEqual(fake.calls[0].get("keep_alive"), brain.AI_KEEP_ALIVE)

    def test_timeout_that_consumes_the_budget_is_not_retried(self):
        # A real read timeout blocks until the whole budget is spent. brain
        # must NOT retry (that would double the wait) and must fall back to
        # the fast budget message. Uses a 1s budget so the test stays fast.
        budget = 1.0

        def hang_then_timeout(**kw):
            time.sleep(budget)
            raise TimeoutError("Read timed out")

        fake = _FakeClient(hang_then_timeout)
        with mock.patch.object(brain, "AI_RESPONSE_BUDGET_SECONDS", budget), \
                mock.patch.object(brain, "_get_client", return_value=fake):
            started = time.monotonic()
            answer = brain.ask_ai("hello")
            elapsed = time.monotonic() - started
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("reply budget", answer)
        self.assertLess(elapsed, budget + 2.0)

    def test_instant_timeout_failure_still_uses_the_single_retry(self):
        # A timeout that fails immediately leaves budget remaining, so the
        # deadline-aware policy legitimately spends its one retry.
        fake = _FakeClient(lambda **kw: (_ for _ in ()).throw(TimeoutError("Read timed out")))
        with mock.patch.object(brain, "_get_client", return_value=fake):
            answer = brain.ask_ai("hello")
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("reply budget", answer)

    def test_transient_error_is_retried_once_while_budget_remains(self):
        # Quick transient network failures still deserve the single retry.
        fake = _FakeClient(
            lambda **kw: (_ for _ in ()).throw(ConnectionError("connection refused"))
        )
        with mock.patch.object(brain, "_get_client", return_value=fake):
            started = time.monotonic()
            answer = brain.ask_ai("hello")
            elapsed = time.monotonic() - started
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("something went wrong", answer)
        self.assertLess(elapsed, brain.AI_RESPONSE_BUDGET_SECONDS)

    def test_empty_question_answers_instantly(self):
        started = time.monotonic()
        self.assertEqual(brain.ask_ai("   "), "Please say something!")
        self.assertLess(time.monotonic() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
