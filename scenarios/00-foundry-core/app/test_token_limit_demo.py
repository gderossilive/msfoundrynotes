import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import chat_completions
import token_limit_demo as demo


class FakeStatusError(Exception):
    def __init__(self, status: int, headers: dict[str, str]) -> None:
        super().__init__("status error")
        self.status_code = status
        self.response = SimpleNamespace(headers=headers)


def client_returning(outcome: object) -> Mock:
    client = Mock()
    create = client.chat.completions.with_raw_response.create
    if isinstance(outcome, Exception):
        create.side_effect = outcome
    else:
        create.return_value = outcome
    return client


def observation(caller: str, status: int, retry_after: int | None = None) -> demo.Observation:
    return demo.Observation(caller, status, 80 if status == 200 else None, 100, retry_after, 5, "t")


class SendRequestTests(unittest.TestCase):
    def test_reads_budget_headers_from_success(self) -> None:
        response = SimpleNamespace(
            status_code=200,
            headers={demo.CONSUMED_HEADER: "79", demo.REMAINING_HEADER: "521"},
        )

        result = demo.send_request(client_returning(response), "gpt-5-mini", "A")

        self.assertEqual((result.status, result.consumed_tokens, result.remaining_tokens), (200, 79, 521))
        self.assertIsNone(result.retry_after_seconds)

    def test_returns_429_instead_of_raising(self) -> None:
        error = FakeStatusError(429, {"retry-after": "37"})

        result = demo.send_request(client_returning(error), "gpt-5-mini", "A")

        self.assertEqual((result.status, result.retry_after_seconds), (429, 37))

    def test_bounds_completion_and_never_stores_prompt(self) -> None:
        client = client_returning(SimpleNamespace(status_code=200, headers={}))

        result = demo.send_request(client, "gpt-5-mini", "A")

        kwargs = client.chat.completions.with_raw_response.create.call_args.kwargs
        self.assertEqual(kwargs["max_completion_tokens"], demo.MAX_COMPLETION_TOKENS)
        self.assertNotIn(demo.PROMPT, json.dumps(result.__dict__))

    def test_connection_failures_are_not_swallowed(self) -> None:
        with self.assertRaises(ConnectionError):
            demo.send_request(client_returning(ConnectionError("down")), "gpt-5-mini", "A")

    def test_ignores_malformed_header_values(self) -> None:
        self.assertIsNone(demo.header_int({"x": "not-a-number"}, "x"))
        self.assertIsNone(demo.header_int({}, "x"))
        self.assertEqual(demo.header_int({"x": "12.0"}, "x"), 12)


class RunDemoTests(unittest.TestCase):
    def test_full_sequence_passes(self) -> None:
        a_responses = iter([observation("A", 200), observation("A", 200), observation("A", 429, 30), observation("A", 200)])
        sleeps: list[float] = []

        report = demo.run_demo(
            lambda: next(a_responses), lambda: observation("B", 200), sleeps.append, max_calls=10
        )

        self.assertTrue(report["passed"])
        self.assertEqual(sleeps, [31])
        self.assertEqual([item["caller"] for item in report["observations"]], ["A", "A", "A", "B", "A"])

    def test_limit_never_reached_fails_without_touching_caller_b(self) -> None:
        send_b = Mock()

        report = demo.run_demo(lambda: observation("A", 200), send_b, Mock(), max_calls=3)

        self.assertFalse(report["passed"])
        self.assertFalse(report["verdict"]["limit_enforced"])
        self.assertIsNone(report["verdict"]["caller_b_unaffected"])
        send_b.assert_not_called()
        self.assertEqual(len(report["observations"]), 3)

    def test_shared_budget_is_reported_as_not_isolated(self) -> None:
        report = demo.run_demo(
            lambda: observation("A", 429, 10), lambda: observation("B", 429, 10), Mock(), max_calls=2
        )

        self.assertFalse(report["verdict"]["caller_b_unaffected"])
        self.assertFalse(report["passed"])

    def test_unexpected_status_stops_the_burst(self) -> None:
        calls = []

        def send_a() -> demo.Observation:
            calls.append(1)
            return observation("A", 403)

        report = demo.run_demo(send_a, Mock(), Mock(), max_calls=10)

        self.assertEqual(len(calls), 1)
        self.assertFalse(report["passed"])

    def test_retry_wait_is_bounded_and_defaults_when_missing(self) -> None:
        self.assertEqual(demo.retry_wait_seconds(None), demo.DEFAULT_RETRY_AFTER_SECONDS + 1)
        self.assertEqual(demo.retry_wait_seconds(0), demo.DEFAULT_RETRY_AFTER_SECONDS + 1)
        self.assertEqual(demo.retry_wait_seconds(5), 6)
        self.assertEqual(demo.retry_wait_seconds(10_000), demo.MAX_RETRY_WAIT_SECONDS + 1)


class MainTests(unittest.TestCase):
    def test_requires_existing_second_caller_profile(self) -> None:
        deployment = chat_completions.Deployment("00c", "acct", "gpt-5-mini", "https://a.azure-api.net/openai/v1/")
        with patch("token_limit_demo.load_deployment", return_value=deployment):
            code = demo.main(["--environment", "dev", "--caller-b-config-dir", "/nonexistent/profile"])

        self.assertEqual(code, 2)

    def test_00a_gateway_scenario_is_selectable(self) -> None:
        deployment = chat_completions.Deployment("00a", "acct", "gpt-4.1-mini", "https://a.azure-api.net/openai/v1/")
        with (
            patch("token_limit_demo.load_deployment", return_value=deployment) as load,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = demo.main(
                ["--environment", "dev", "--scenario", "00a", "--caller-b-config-dir", "/nonexistent/profile"]
            )

        self.assertEqual(code, 2)
        load.assert_called_once_with("dev", "00a")

    def test_rejects_unbounded_call_count(self) -> None:
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            demo.parse_args(["--environment", "dev", "--caller-b-config-dir", "x", "--max-calls", "51"])

    def test_writes_report_without_prompt_or_tokens(self) -> None:
        deployment = chat_completions.Deployment("00c", "acct", "gpt-5-mini", "https://a.azure-api.net/openai/v1/")
        report = {
            "observations": [observation("A", 200).__dict__],
            "waited_seconds": None,
            "verdict": {"limit_enforced": False, "caller_b_unaffected": None, "caller_a_recovered": None},
            "passed": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with (
                patch("token_limit_demo.load_deployment", return_value=deployment),
                patch("token_limit_demo.create_client"),
                patch("token_limit_demo.run_demo", return_value=report),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = demo.main(
                    ["--environment", "dev", "--caller-b-config-dir", directory, "--output", str(output)]
                )
            written = output.read_text(encoding="utf-8")

        self.assertEqual(code, 1)
        self.assertNotIn(demo.PROMPT, written)
        self.assertNotIn("Bearer", written)


if __name__ == "__main__":
    unittest.main()
