import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import chat_completions
import usage_report as report

A_ID = "11111111-1111-1111-1111-111111111111"
B_ID = "22222222-2222-2222-2222-222222222222"
WORKSPACE = "33333333-3333-3333-3333-333333333333"
ACCOUNT = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/acct"
LABELS = {A_ID: "A", B_ID: "B"}


def rows() -> list[dict]:
    return [
        {"caller": A_ID.upper(), "metric": "Prompt Tokens", "tokens": 100.0},
        {"caller": A_ID, "metric": "Completion Tokens", "tokens": 500.0},
        {"caller": A_ID, "metric": "Completion Reasoning Tokens", "tokens": 480.0},
        {"caller": A_ID, "metric": "Total Tokens", "tokens": 600.0},
        {"caller": B_ID, "metric": "Prompt Tokens", "tokens": 10.0},
        {"caller": B_ID, "metric": "Completion Tokens", "tokens": 60.0},
        {"caller": B_ID, "metric": "Completion Reasoning Tokens", "tokens": 50.0},
        {"caller": B_ID, "metric": "Total Tokens", "tokens": 70.0},
    ]


class LabelTests(unittest.TestCase):
    def test_accepts_labelled_guids_case_insensitively(self) -> None:
        self.assertEqual(report.parse_caller_labels([f"A={A_ID.upper()}"]), {A_ID: "A"})

    def test_rejects_bad_labels(self) -> None:
        for value in ("A", "A=not-a-guid", f"=={A_ID}", f"bad/label={A_ID}", f"={A_ID}"):
            with self.assertRaises(chat_completions.ConfigurationError):
                report.parse_caller_labels([value])


class AggregationTests(unittest.TestCase):
    def test_groups_by_label_and_kind(self) -> None:
        usage = report.aggregate_gateway_rows(rows(), LABELS)

        self.assertEqual(usage["A"], {"prompt": 100, "completion": 500, "reasoning": 480, "total": 600})
        self.assertEqual(usage["B"]["total"], 70)

    def test_detail_metrics_do_not_inflate_prompt_or_completion(self) -> None:
        noisy = rows() + [
            {"caller": A_ID, "metric": "Prompt Cached Tokens", "tokens": 90.0},
            {"caller": A_ID, "metric": "Completion Audio Tokens", "tokens": 90.0},
        ]

        usage = report.aggregate_gateway_rows(noisy, LABELS)

        self.assertEqual((usage["A"]["prompt"], usage["A"]["completion"]), (100, 500))

    def test_unknown_caller_is_shortened_not_printed_in_full(self) -> None:
        usage = report.aggregate_gateway_rows(rows(), {})

        self.assertIn("unlabeled-11111111", usage)
        self.assertFalse(any(A_ID in label for label in usage))

    def test_ignores_unrelated_metrics_and_empty_callers(self) -> None:
        usage = report.aggregate_gateway_rows(
            [{"caller": A_ID, "metric": "Requests", "tokens": 5}, {"caller": "", "metric": "Total Tokens", "tokens": 5}],
            LABELS,
        )

        self.assertEqual(usage, {})

    def test_query_is_bounded_to_the_window_and_the_caller_dimension(self) -> None:
        query = report.build_usage_query("2026-11-02T10:00:00Z", "2026-11-02T11:00:00Z")

        self.assertIn("datetime(2026-11-02T10:00:00Z) .. datetime(2026-11-02T11:00:00Z)", query)
        self.assertTrue(query.startswith("AppMetrics"))
        self.assertIn('Properties["Caller"]', query)
        self.assertIn('"Completion Reasoning Tokens"', query)


class WindowTests(unittest.TestCase):
    def test_aligns_to_whole_minutes(self) -> None:
        since = datetime(2026, 11, 2, 14, 12, 46, tzinfo=timezone.utc)
        until = datetime(2026, 11, 2, 14, 30, 5, tzinfo=timezone.utc)

        aligned_since, aligned_until = report.align_window(since, until)

        self.assertEqual(report.iso(aligned_since), "2026-11-02T14:12:00Z")
        self.assertEqual(report.iso(aligned_until), "2026-11-02T14:31:00Z")

    def test_whole_minutes_are_unchanged(self) -> None:
        moment = datetime(2026, 11, 2, 14, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(report.align_window(moment, moment + timedelta(minutes=5)), (moment, moment + timedelta(minutes=5)))


class CostTests(unittest.TestCase):
    def test_cost_needs_both_prices(self) -> None:
        usage = {"prompt": 2_000_000, "completion": 1_000_000, "total": 3_000_000}

        self.assertIsNone(report.estimate_cost(usage, None, 1.0))
        self.assertEqual(report.estimate_cost(usage, 0.5, 2.0), 3.0)

    def test_arguments_reject_a_single_or_negative_price(self) -> None:
        for extra in (["--price-input-per-million", "1"], ["--price-input-per-million", "-1", "--price-output-per-million", "1"]):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                report.parse_args(["--environment", "dev", *extra])


class ReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = report.aggregate_gateway_rows(rows(), LABELS)

    def test_matches_model_side_totals(self) -> None:
        result = report.reconcile(self.gateway, {"input": 110, "output": 560}, None)

        self.assertTrue(result["gateway_matches_model"])
        self.assertEqual((result["model_minus_gateway_input"], result["model_minus_gateway_output"]), (0, 0))

    def test_reports_difference_with_model_side_totals(self) -> None:
        result = report.reconcile(self.gateway, {"input": 110, "output": 561}, None)

        self.assertFalse(result["gateway_matches_model"])

    def test_quantifies_traffic_the_gateway_did_not_see(self) -> None:
        # A direct call to the model (bypass) shows up only in the model-side totals.
        result = report.reconcile(self.gateway, {"input": 110 + 11, "output": 560 + 10}, None)

        self.assertFalse(result["gateway_matches_model"])
        self.assertEqual((result["model_minus_gateway_input"], result["model_minus_gateway_output"]), (11, 10))

    def test_compares_response_headers_per_caller(self) -> None:
        ok = report.reconcile(self.gateway, None, {"A": 600, "B": 70})
        bad = report.reconcile(self.gateway, None, {"A": 600, "B": 71})

        self.assertTrue(ok["response_headers_match_gateway"])
        self.assertEqual(bad["response_header_mismatches"], ["B"])

    def test_demo_totals_ignore_rejected_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.json"
            path.write_text(
                json.dumps(
                    {
                        "observations": [
                            {"caller": "A", "status": 200, "consumed_tokens": 77},
                            {"caller": "A", "status": 429, "consumed_tokens": None},
                            {"caller": "B", "status": 200, "consumed_tokens": 77},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(report.load_demo_totals(path), {"A": 77, "B": 77})


class ModelMetricsTests(unittest.TestCase):
    def test_sums_platform_series(self) -> None:
        response = {
            "value": [
                {"name": {"value": "InputTokens"}, "timeseries": [{"data": [{"total": 100}, {"total": 10}, {}]}]},
                {"name": {"value": "OutputTokens"}, "timeseries": [{"data": [{"total": 560.0}]}]},
            ]
        }
        with patch("usage_report.run_az", return_value=response) as run:
            totals = report.query_model_tokens(ACCOUNT, "gpt-5-mini", "s", "e")

        self.assertEqual(totals, {"input": 110, "output": 560})
        self.assertIn("ModelDeploymentName eq 'gpt-5-mini'", run.call_args.args[0])


class MainTests(unittest.TestCase):
    def deployment(self) -> chat_completions.Deployment:
        return chat_completions.Deployment("00c", "acct", "gpt-5-mini", "https://a.azure-api.net/openai/v1/")

    def run_main(self, values: dict, gateway_rows: list[dict], output: Path, extra: list[str] | None = None) -> int:
        with (
            patch("usage_report.load_deployment", return_value=self.deployment()),
            patch("usage_report.read_environment_values", return_value=values),
            patch("usage_report.query_gateway_usage", return_value=gateway_rows),
            patch("usage_report.query_model_tokens", return_value={"input": 110, "output": 560}),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return report.main(
                ["--environment", "dev", "--caller", f"A={A_ID}", "--caller", f"B={B_ID}", "--output", str(output), *(extra or [])]
            )

    def test_requires_usage_metrics_to_be_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code = self.run_main({"AZURE_AI_ACCOUNT_ID": ACCOUNT}, rows(), Path(directory) / "r.json")

        self.assertEqual(code, 2)

    def test_empty_window_asks_to_retry(self) -> None:
        values = {"AZURE_USAGE_WORKSPACE_CUSTOMER_ID": WORKSPACE, "AZURE_AI_ACCOUNT_ID": ACCOUNT}
        with tempfile.TemporaryDirectory() as directory:
            code = self.run_main(values, [], Path(directory) / "r.json")

        self.assertEqual(code, 3)

    def test_successful_report_has_no_object_ids(self) -> None:
        values = {"AZURE_USAGE_WORKSPACE_CUSTOMER_ID": WORKSPACE, "AZURE_AI_ACCOUNT_ID": ACCOUNT}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "r.json"
            code = self.run_main(
                values, rows(), output, ["--price-input-per-million", "1", "--price-output-per-million", "2"]
            )
            written = output.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertNotIn(A_ID, written)
        self.assertNotIn(B_ID, written)
        self.assertTrue(json.loads(written)["reconciliation"]["gateway_matches_model"])

    def test_mismatch_returns_nonzero(self) -> None:
        values = {"AZURE_USAGE_WORKSPACE_CUSTOMER_ID": WORKSPACE, "AZURE_AI_ACCOUNT_ID": ACCOUNT}
        other = [dict(item, tokens=item["tokens"] + 1) for item in rows()]
        with tempfile.TemporaryDirectory() as directory:
            code = self.run_main(values, other, Path(directory) / "r.json")

        self.assertEqual(code, 1)

    def test_00a_gateway_scenario_is_selectable(self) -> None:
        deployment = chat_completions.Deployment("00a", "acct", "gpt-4.1-mini", "https://a.azure-api.net/openai/v1/")
        values = {"AZURE_USAGE_WORKSPACE_CUSTOMER_ID": WORKSPACE, "AZURE_AI_ACCOUNT_ID": ACCOUNT}
        with (
            patch("usage_report.load_deployment", return_value=deployment) as load,
            patch("usage_report.read_environment_values", return_value=values) as read,
            patch("usage_report.query_gateway_usage", return_value=[]),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = report.main(["--environment", "dev", "--scenario", "00a"])

        self.assertEqual(code, 3)
        load.assert_called_once_with("dev", "00a")
        read.assert_called_once_with("dev", "00a")

    def test_window_must_be_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code = self.run_main(
                {}, rows(), Path(directory) / "r.json", ["--since", "2026-11-02T11:00:00Z", "--until", "2026-11-02T10:00:00Z"]
            )

        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
