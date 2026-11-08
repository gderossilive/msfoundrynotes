import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import monitor_model as monitoring
from benchmark_documents import load_documents
from chat_completions import ConfigurationError, Deployment
from test_benchmark_documents import evaluation_client


def raw_response(content: str, *, usage=True, finish_reason="stop", refusal=None):
    completion = SimpleNamespace(
        id="completion-1",
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120) if usage else None,
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content, refusal=refusal),
        )],
    )
    return SimpleNamespace(
        status_code=200, headers={"apim-request-id": "request-1"}, parse=lambda: completion,
    )


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.documents = load_documents()
        self.client = Mock()
        self.client.chat.completions.with_raw_response.create.side_effect = [
            raw_response(json.dumps(document.expected)) for document in self.documents
        ]

    def test_exactly_ten_bounded_non_streaming_calls(self):
        results, quality, safety = monitoring.collect_observations(
            self.client, "gpt-4.1-mini", self.documents, "run-1",
        )
        calls = self.client.chat.completions.with_raw_response.create.call_args_list
        self.assertEqual(len(calls), 10)
        for call, document in zip(calls, self.documents):
            self.assertEqual(call.kwargs["max_completion_tokens"], 128)
            self.assertFalse(call.kwargs["stream"])
            self.assertEqual(call.kwargs["messages"][1]["content"], document.text)
        self.assertEqual(len(quality), 10)
        self.assertEqual(len(safety), 10)
        self.assertEqual(results[0]["tokens"], {"input": 100, "output": 20, "total": 120})
        self.assertEqual(results[0]["request_id"], "request-1")
        self.assertGreaterEqual(results[0]["client_duration_ms"], 0)
        for document in self.documents:
            self.assertNotIn(document.text, json.dumps(results))
        self.assertNotIn("predicted", json.dumps(results))

    def test_other_sample_sizes_are_rejected_before_calls(self):
        with self.assertRaises(ConfigurationError):
            monitoring.collect_observations(self.client, "model", self.documents[:1], "run")
        self.client.chat.completions.with_raw_response.create.assert_not_called()

    def test_missing_usage_is_not_zero(self):
        self.client.chat.completions.with_raw_response.create.side_effect = None
        self.client.chat.completions.with_raw_response.create.return_value = raw_response(
            json.dumps(self.documents[0].expected), usage=False,
        )
        results, _, _ = monitoring.collect_observations(self.client, "model", self.documents, "run")
        self.assertEqual(results[0]["tokens"], {"input": None, "output": None, "total": None})

    def test_invalid_classification_has_http_success_but_no_quality_row(self):
        self.client.chat.completions.with_raw_response.create.side_effect = [
            raw_response("private response text"),
            *[raw_response(json.dumps(document.expected)) for document in self.documents[1:]],
        ]
        with redirect_stderr(io.StringIO()) as errors:
            results, quality, safety = monitoring.collect_observations(
                self.client, "model", self.documents, "run",
            )
        self.assertEqual(results[0]["http_status"], 200)
        self.assertEqual(results[0]["status"], "response_error")
        self.assertEqual(len(quality), 9)
        self.assertEqual(len(safety), 10)
        self.assertNotIn("private response text", errors.getvalue() + json.dumps(results))

    def test_refusal_is_separate_from_request_failure(self):
        self.client.chat.completions.with_raw_response.create.side_effect = [
            raw_response(None, refusal="Benign refusal."),
            *[raw_response(json.dumps(document.expected)) for document in self.documents[1:]],
        ]
        with redirect_stderr(io.StringIO()):
            results, quality, safety = monitoring.collect_observations(
                self.client, "model", self.documents, "run",
            )
        self.assertEqual(results[0]["status"], "response_error")
        self.assertEqual(len(quality), 9)
        self.assertEqual(safety[0]["response"], "Benign refusal.")

    def test_http_error_is_sanitized_and_not_retried(self):
        import httpx
        from openai import BadRequestError

        error = BadRequestError(
            "sensitive error body",
            response=httpx.Response(400, request=httpx.Request("POST", "https://example.test")),
            body={"message": "sensitive body"},
        )
        self.client.chat.completions.with_raw_response.create.side_effect = [
            error, *[raw_response(json.dumps(document.expected)) for document in self.documents[1:]],
        ]
        with redirect_stderr(io.StringIO()) as errors:
            results, quality, safety = monitoring.collect_observations(
                self.client, "model", self.documents, "run",
            )
        self.assertEqual(results[0]["http_status"], 400)
        self.assertEqual(results[0]["status"], "request_error")
        self.assertEqual(len(quality), 9)
        self.assertEqual(len(safety), 9)
        self.assertEqual(self.client.chat.completions.with_raw_response.create.call_count, 10)
        self.assertNotIn("sensitive", errors.getvalue() + json.dumps(results))

    def test_span_attributes_never_include_messages_or_credentials(self):
        try:
            from opentelemetry import trace
        except ImportError:
            self.skipTest("Optional tracing dependencies are not installed.")
        span = Mock()
        span.get_span_context.return_value = SimpleNamespace(trace_id=1)
        result = {
            "index": 1, "status": "valid", "client_duration_ms": 12,
            "http_status": 200, "response_id": "completion", "request_id": "request",
            "tokens": {"input": 10, "output": 5},
            "prompt": "secret prompt", "response": "secret response", "api_key": "secret key",
        }
        monitoring.annotate_span(span, result, "model", "run")
        attributes = dict(call.args for call in span.set_attribute.call_args_list)
        self.assertEqual(attributes["gen_ai.usage.input_tokens"], 10)
        self.assertNotIn("secret", json.dumps(attributes))
        self.assertEqual(result["trace_id"], "00000000000000000000000000000001")
        span.set_status.assert_called_once_with(trace.StatusCode.OK)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.deployment = Deployment("00a", "account", "model", resource_group="rg", subscription_id="sub")
        self.resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Insights/components/app"

    @patch("monitor_model.subprocess.run")
    def test_connection_is_loaded_without_printing_it(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "true", ""),
            subprocess.CompletedProcess([], 0, self.resource_id, ""),
            subprocess.CompletedProcess([], 0, "InstrumentationKey=configuration", ""),
        ]
        self.assertEqual(
            monitoring.load_connection_string("dev", self.deployment),
            "InstrumentationKey=configuration",
        )
        self.assertEqual(run.call_args.args[0][0:3], ["az", "resource", "show"])

    @patch("monitor_model.subprocess.run")
    def test_foreign_or_missing_resource_is_rejected(self, run):
        for resource_id in ("", self.resource_id.replace("/rg/", "/another/"), self.resource_id + "/child"):
            run.side_effect = [
                subprocess.CompletedProcess([], 0, "true", ""),
                subprocess.CompletedProcess([], 0, resource_id, ""),
            ]
            with self.subTest(resource_id=resource_id), self.assertRaises(ConfigurationError):
                monitoring.load_connection_string("dev", self.deployment)

    @patch("monitor_model.subprocess.run")
    def test_disabled_profile_rejects_stale_resource_outputs(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "false", "")
        with self.assertRaisesRegex(ConfigurationError, "monitoring-enabled"):
            monitoring.load_connection_string("dev", self.deployment)
        self.assertEqual(run.call_count, 1)

    @patch("monitor_model.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_cli_is_explicit(self, run):
        with self.assertRaisesRegex(ConfigurationError, "Azure CLI and azd"):
            monitoring.load_connection_string("dev", self.deployment)

    def test_failed_export_is_explicit_and_provider_is_shutdown(self):
        telemetry = monitoring.Telemetry.__new__(monitoring.Telemetry)
        telemetry.provider = Mock()
        telemetry.provider.force_flush.return_value = True
        telemetry.exporter = SimpleNamespace(failed=True, exported=0)
        with self.assertRaisesRegex(RuntimeError, "Trace export failed"):
            telemetry.close()
        telemetry.provider.shutdown.assert_called_once()

    def test_flush_timeout_is_not_success(self):
        telemetry = monitoring.Telemetry.__new__(monitoring.Telemetry)
        telemetry.provider = Mock()
        telemetry.provider.force_flush.return_value = False
        telemetry.exporter = SimpleNamespace(failed=False, exported=0)
        with self.assertRaises(RuntimeError):
            telemetry.close()


class EvaluationTests(unittest.TestCase):
    def test_safety_uses_existing_pairs_not_a_model_target(self):
        client = evaluation_client(
            1, {name: 1 for name in monitoring.SAFETY_EVALUATORS},
        )
        with patch("benchmark_documents.time.sleep"):
            result = monitoring.run_safety_evaluation(
                client, [{"query": "Synthetic invoice.", "response": "Invoice"}],
            )
        criteria = client.evals.create.call_args.kwargs["testing_criteria"]
        self.assertEqual(
            [item["evaluator_name"] for item in criteria],
            [f"builtin.{name}" for name in monitoring.SAFETY_EVALUATORS],
        )
        self.assertEqual(set(result["pass_rate"]), set(monitoring.SAFETY_EVALUATORS))
        self.assertNotIn("target", client.evals.runs.create.call_args.kwargs)
        client.chat.completions.create.assert_not_called()

    def test_empty_safety_rows_do_not_create_an_evaluation(self):
        client = Mock()
        with self.assertRaises(ConfigurationError):
            monitoring.run_safety_evaluation(client, [])
        client.evals.create.assert_not_called()


class MainTests(unittest.TestCase):
    def run_main(self, *flags, responses=None, evaluator=None, telemetry=None):
        documents = load_documents()
        client = Mock()
        client.with_options.return_value = client
        client.chat.completions.with_raw_response.create.side_effect = responses or [
            raw_response(json.dumps(document.expected)) for document in documents
        ]
        deployment = Deployment("00a", "account", "model", project_name="project")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.json"
            with (
                patch("monitor_model.load_deployment", return_value=deployment),
                patch("monitor_model.create_openai_client", side_effect=[client, evaluator or Mock()]),
                patch("monitor_model.Telemetry", return_value=telemetry),
                patch("monitor_model.load_connection_string", return_value="private configuration"),
                redirect_stdout(io.StringIO()) as stdout,
                redirect_stderr(io.StringIO()) as stderr,
            ):
                code = monitoring.main(["--environment", "dev", "--output", str(path), *flags])
            return code, json.loads(path.read_text()), client, stdout.getvalue() + stderr.getvalue()

    def test_default_run_is_bounded_and_does_not_claim_evaluation_or_tracing(self):
        code, report, client, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(report["scenario"], "00a")
        self.assertEqual(report["lane"], "a")
        self.assertEqual(report["coverage"], 1)
        self.assertEqual(report["quality"]["evaluation_status"], "not_requested")
        self.assertEqual(report["tracing"]["status"], "not_requested")
        client.with_options.assert_called_once_with(max_retries=0, timeout=60.0)
        client.close.assert_called_once()

    def test_quality_evaluation_does_not_repeat_inference(self):
        evaluator = evaluation_client(10)
        with patch("benchmark_documents.time.sleep"):
            code, report, client, _ = self.run_main("--evaluate", evaluator=evaluator)
        self.assertEqual(code, 0)
        self.assertEqual(report["quality"]["evaluation_status"], "completed")
        self.assertEqual(client.chat.completions.with_raw_response.create.call_count, 10)
        evaluator.close.assert_called_once()

    def test_partial_run_exits_nonzero_with_coverage(self):
        documents = load_documents()
        responses = [
            raw_response("invalid"),
            *[raw_response(json.dumps(document.expected)) for document in documents[1:]],
        ]
        code, report, _, _ = self.run_main(responses=responses)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["coverage"], 0.9)

    def test_evaluation_failure_preserves_operational_results_without_sensitive_error(self):
        evaluator = Mock()
        evaluator.evals.create.side_effect = RuntimeError("sensitive evaluation content")
        code, report, _, output = self.run_main("--evaluate", evaluator=evaluator)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["quality"]["evaluation_status"], "failed")
        self.assertEqual(len(report["results"]), 10)
        self.assertNotIn("sensitive", json.dumps(report) + output)

    def test_trace_failure_cannot_be_reported_as_completed(self):
        telemetry = Mock()
        telemetry.span.return_value = null_span()
        telemetry.close.side_effect = RuntimeError("export failed")
        code, report, _, _ = self.run_main("--trace", telemetry=telemetry)
        self.assertEqual(code, 1)
        self.assertEqual(report["tracing"]["status"], "failed")
        self.assertEqual(report["status"], "failed")

    @patch("monitor_model.load_deployment", side_effect=ConfigurationError("secret config"))
    def test_configuration_failure_is_reported_without_inference(self, load):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.json"
            with patch("monitor_model.create_openai_client") as create, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = monitoring.main(["--environment", "bad", "--output", str(path)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(path.read_text())["status"], "failed")
            create.assert_not_called()


def null_span():
    from contextlib import nullcontext
    return nullcontext(None)


class SDKTelemetryTests(unittest.TestCase):
    def setUp(self):
        try:
            from azure.monitor.opentelemetry import exporter
            from opentelemetry.sdk.trace.export import SpanExportResult
        except ImportError:
            self.skipTest("Optional tracing dependencies are not installed.")
        self.result_type = SpanExportResult

    def test_real_span_pipeline_exports_ten_content_free_spans(self):
        exporter = Mock()
        exporter.export.return_value = self.result_type.SUCCESS
        with (
            patch("azure.monitor.opentelemetry.exporter.AzureMonitorTraceExporter", return_value=exporter) as create,
            patch.dict("os.environ", {
                "OTEL_RESOURCE_ATTRIBUTES": "private.content=secret",
                "OTEL_TRACES_SAMPLER": "always_off",
            }),
        ):
            telemetry = monitoring.Telemetry("private configuration", "run-1")
            client = Mock()
            documents = load_documents()
            client.chat.completions.with_raw_response.create.side_effect = [
                raw_response(json.dumps(document.expected)) for document in documents
            ]
            results, _, _ = monitoring.collect_observations(
                client, "model", documents, "run-1", telemetry,
            )
            self.assertEqual(telemetry.close(), 10)
        self.assertTrue(create.call_args.kwargs["disable_offline_storage"])
        self.assertIs(create.call_args.kwargs["tracer_provider"], telemetry.provider)
        self.assertIsNotNone(create.call_args.kwargs["credential"])
        self.assertEqual(exporter.export.call_count, 10)
        for call, result in zip(exporter.export.call_args_list, results):
            span = call.args[0][0]
            self.assertNotIn("secret", json.dumps(dict(span.resource.attributes)))
            self.assertNotIn("private configuration", json.dumps(dict(span.attributes)))
            self.assertNotIn("gen_ai.prompt", span.attributes)
            self.assertEqual(f"{span.context.trace_id:032x}", result["trace_id"])
            self.assertEqual(span.attributes["gen_ai.request.max_tokens"], 128)
            self.assertEqual(span.events, ())

    def test_export_failure_from_the_sdk_is_not_silently_accepted(self):
        exporter = Mock()
        exporter.export.return_value = self.result_type.FAILURE
        with patch("azure.monitor.opentelemetry.exporter.AzureMonitorTraceExporter", return_value=exporter):
            telemetry = monitoring.Telemetry("configuration", "run")
            with telemetry.span("model"):
                pass
            with self.assertRaisesRegex(RuntimeError, "Trace export failed"):
                telemetry.close()
