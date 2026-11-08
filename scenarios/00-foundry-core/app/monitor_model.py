#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from benchmark_documents import (
    SYSTEM_PROMPT,
    Document,
    ResponseError,
    evaluation_row,
    load_documents,
    parse_classification,
    response_format,
    run_dataset_evaluation,
    run_foundry_evaluation,
)
from chat_completions import (
    LANE_DIRECTORIES,
    ConfigurationError,
    Deployment,
    create_openai_client,
    load_deployment,
    request_error_types,
)

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "monitoring-results.json"
OUTPUT_TOKEN_LIMIT = 128
SAFETY_EVALUATORS = ("violence", "self_harm", "hate_unfairness", "sexual")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_connection_string(environment: str, deployment: Deployment) -> str:
    try:
        enabled = subprocess.run(
            ["azd", "env", "get-value", "AZURE_MONITORING_ENABLED", "--environment", environment],
            cwd=LANE_DIRECTORIES["00a"], capture_output=True, text=True, check=False,
        )
        if enabled.returncode or enabled.stdout.strip().lower() != "true":
            raise ConfigurationError("Provision the monitoring-enabled 00a profile before using --trace.")
        result = subprocess.run(
            [
                "azd", "env", "get-value", "AZURE_MONITORING_APPLICATION_INSIGHTS_ID",
                "--environment", environment,
            ],
            cwd=LANE_DIRECTORIES["00a"], capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise ConfigurationError("Cannot read the monitoring resource ID from the 00a environment.")
        resource_id = result.stdout.strip()
        prefix = (
            f"/subscriptions/{deployment.subscription_id}/resourceGroups/"
            f"{deployment.resource_group}/providers/Microsoft.Insights/components/"
        )
        if (
            not resource_id.lower().startswith(prefix.lower())
            or not re.fullmatch(r"[a-zA-Z0-9._-]+", resource_id[len(prefix):])
        ):
            raise ConfigurationError("Enable monitoring in this 00a environment before using --trace.")
        result = subprocess.run(
            [
                "az", "resource", "show", "--ids", resource_id,
                "--subscription", deployment.subscription_id,
                "--api-version", "2020-02-02",
                "--query", "properties.ConnectionString", "--output", "tsv",
            ],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as exc:
        raise ConfigurationError("Azure CLI and azd are required for cloud tracing.") from exc
    if result.returncode or not result.stdout.strip():
        raise ConfigurationError("Cannot read Application Insights configuration; check resource access.")
    return result.stdout.strip()


class Telemetry:
    def __init__(self, connection_string: str, run_id: str) -> None:
        from azure.identity import AzureCliCredential
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON

        class CheckedExporter(SpanExporter):
            def __init__(self, exporter: SpanExporter) -> None:
                self.exporter = exporter
                self.failed = False
                self.exported = 0

            def export(self, spans: Sequence[Any]) -> Any:
                result = self.exporter.export(spans)
                if result != SpanExportResult.SUCCESS:
                    self.failed = True
                else:
                    self.exported += len(spans)
                return result

            def shutdown(self) -> None:
                self.exporter.shutdown()

        self.provider = TracerProvider(
            resource=Resource({
                "service.name": "foundry-notes-00a-monitoring",
                "service.instance.id": run_id,
            }),
            sampler=ALWAYS_ON,
        )
        self.exporter = CheckedExporter(
            AzureMonitorTraceExporter(
                connection_string=connection_string,
                credential=AzureCliCredential(),
                disable_offline_storage=True,
                tracer_provider=self.provider,
            )
        )
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("foundry-notes.model-monitoring")

    def span(self, model: str) -> Any:
        from opentelemetry.trace import SpanKind

        return self.tracer.start_as_current_span(
            f"chat {model}", kind=SpanKind.CLIENT,
            record_exception=False, set_status_on_exception=False,
        )

    def close(self) -> int:
        try:
            flushed = self.provider.force_flush()
        finally:
            self.provider.shutdown()
        if not flushed or self.exporter.failed:
            raise RuntimeError("Trace export failed; no successful cloud tracing is claimed.")
        return self.exporter.exported


def token_usage(completion: Any) -> dict[str, int | None]:
    usage = completion.usage
    result = {}
    for key, attribute in (
        ("input", "prompt_tokens"), ("output", "completion_tokens"), ("total", "total_tokens")
    ):
        value = getattr(usage, attribute, None)
        result[key] = value if type(value) is int and value >= 0 else None
    return result


def annotate_span(span: Any, result: dict[str, Any], model: str, run_id: str) -> None:
    if span is None:
        return
    from opentelemetry.trace import StatusCode

    attributes = {
        "gen_ai.system": "azure.ai.openai",
        "gen_ai.operation.name": "chat",
        "gen_ai.request.model": model,
        "gen_ai.request.max_tokens": OUTPUT_TOKEN_LIMIT,
        "monitoring.run_id": run_id,
        "monitoring.document_index": result["index"],
        "monitoring.response_status": result["status"],
        "monitoring.client_duration_ms": result["client_duration_ms"],
        "http.response.status_code": result["http_status"],
        "gen_ai.response.id": result["response_id"],
        "monitoring.request_id": result["request_id"],
        "gen_ai.usage.input_tokens": result["tokens"]["input"],
        "gen_ai.usage.output_tokens": result["tokens"]["output"],
        "error.type": result.get("error_type"),
    }
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)
    span.set_status(StatusCode.OK if result["status"] == "valid" else StatusCode.ERROR)
    result["trace_id"] = f"{span.get_span_context().trace_id:032x}"


def collect_observations(
    client: Any, model: str, documents: list[Document], run_id: str,
    telemetry: Telemetry | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    if len(documents) != 10:
        raise ConfigurationError("The monitoring demo requires exactly ten synthetic documents.")
    schema = response_format(documents)
    results = []
    quality_rows = []
    safety_rows = []
    for document in documents:
        result = {
            "index": document.index, "started_at": utc_now(),
            "http_status": None, "request_id": None, "response_id": None,
            "trace_id": None, "tokens": dict.fromkeys(("input", "output", "total")),
        }
        context = telemetry.span(model) if telemetry is not None else nullcontext(None)
        with context as span:
            started = time.perf_counter()
            try:
                raw = client.chat.completions.with_raw_response.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": document.text},
                    ],
                    response_format=schema,
                    max_completion_tokens=OUTPUT_TOKEN_LIMIT,
                    stream=False,
                )
                result["client_duration_ms"] = (time.perf_counter() - started) * 1000
                completion = raw.parse()
                result.update(
                    http_status=raw.status_code,
                    request_id=raw.headers.get("x-request-id") or raw.headers.get("apim-request-id"),
                    response_id=completion.id, tokens=token_usage(completion),
                )
                if completion.choices:
                    message = completion.choices[0].message
                    text = message.content or message.refusal
                    if isinstance(text, str) and text.strip():
                        safety_rows.append({
                            "query": document.text, "response": text,
                        })
                prediction = parse_classification(completion, schema)
            except ResponseError:
                result.update(status="response_error", error_type="ResponseError")
            except request_error_types() as exc:
                result.update(
                    status="request_error",
                    error_type=type(exc).__name__,
                    http_status=getattr(exc, "status_code", None),
                    request_id=getattr(exc, "request_id", None),
                )
            else:
                result["status"] = "valid"
                quality_rows.append(evaluation_row(document, prediction))
            if "client_duration_ms" not in result:
                result["client_duration_ms"] = (time.perf_counter() - started) * 1000
            result["ended_at"] = utc_now()
            annotate_span(span, result, model, run_id)
        if result["status"] != "valid":
            print(
                f"Document {document.index}: {result['error_type']} "
                f"(HTTP {result['http_status']}); content omitted.",
                file=sys.stderr,
            )
        results.append(result)
    return results, quality_rows, safety_rows


def run_safety_evaluation(client: Any, rows: list[dict[str, str]]) -> dict[str, Any]:
    criteria = [
        {
            "type": "azure_ai_evaluator", "name": name,
            "evaluator_name": f"builtin.{name}",
            "data_mapping": {"query": "{{item.query}}", "response": "{{item.response}}"},
        }
        for name in SAFETY_EVALUATORS
    ]
    result = run_dataset_evaluation(
        client, "00a-model-monitoring-safety", rows,
        {"query": {"type": "string"}, "response": {"type": "string"}}, criteria,
    )
    result["pass_rate"] = result.pop("accuracy")
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Observe ten synthetic model calls in scenario 00a (level 00, lane a)."
    )
    parser.add_argument("--environment", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--trace", action="store_true", help="Export content-free spans to Azure Monitor.")
    parser.add_argument("--evaluate", action="store_true", help="Submit classification labels to Foundry Evaluation.")
    parser.add_argument(
        "--evaluate-safety", action="store_true",
        help="Submit the synthetic query/response pairs to hosted Foundry safety evaluators.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    telemetry = None
    report: dict[str, Any] = {
        "run_id": str(uuid4()), "scenario": "00a", "level": "00", "lane": "a",
        "started_at": utc_now(), "status": "failed", "model": None,
        "output_token_limit": OUTPUT_TOKEN_LIMIT,
        "max_model_attempts": 10, "automatic_model_retries": 0,
        "quality": {"evaluation_status": "not_requested"},
        "safety": {"evaluation_status": "not_requested"},
        "tracing": {"status": "not_requested"},
        "results": [],
    }
    exit_code = 1
    try:
        if not args.output.parent.is_dir() or args.output.is_dir():
            raise ConfigurationError("The report needs an existing parent directory and a file destination.")
        documents = load_documents()
        deployment = load_deployment(args.environment, "00a")
        report["model"] = deployment.model_deployment_name
        if args.trace:
            report["tracing"] = {"status": "initializing"}
            telemetry = Telemetry(
                load_connection_string(args.environment, deployment), report["run_id"]
            )
        client = create_openai_client(deployment.direct_base_url).with_options(
            max_retries=0, timeout=60.0,
        )
        try:
            results, quality_rows, safety_rows = collect_observations(
                client, deployment.model_deployment_name, documents, report["run_id"], telemetry,
            )
        finally:
            client.close()
        report.update(
            results=results, sample_size=10, valid_responses=len(quality_rows),
            coverage=len(quality_rows) / 10,
        )
        if args.evaluate or args.evaluate_safety:
            evaluation_client = create_openai_client(deployment.project_base_url)
            try:
                if args.evaluate:
                    report["quality"] = {"evaluation_status": "running"}
                    report["quality"] = run_foundry_evaluation(evaluation_client, quality_rows)
                if args.evaluate_safety:
                    report["safety"] = {"evaluation_status": "running"}
                    report["safety"] = {
                        **run_safety_evaluation(evaluation_client, safety_rows),
                        "scored_responses": len(safety_rows),
                        "coverage": len(safety_rows) / 10,
                    }
            finally:
                evaluation_client.close()
        exit_code = 0 if len(quality_rows) == 10 else 1
        report["status"] = "completed" if exit_code == 0 else "partial"
    except ConfigurationError as exc:
        report["error_type"] = type(exc).__name__
        print(f"Monitoring configuration failed ({type(exc).__name__}); check the selected 00a environment.", file=sys.stderr)
        exit_code = 2
    except ImportError:
        report["error_type"] = "ImportError"
        print("Tracing dependencies are missing; install requirements-monitoring.txt.", file=sys.stderr)
        exit_code = 2
    except (*request_error_types(), RuntimeError, ValueError) as exc:
        report["error_type"] = type(exc).__name__
        print(f"Monitoring failed ({type(exc).__name__}); response content omitted.", file=sys.stderr)
    finally:
        if telemetry is not None:
            try:
                exported = telemetry.close()
            except RuntimeError:
                report["status"] = "failed"
                report["tracing"] = {"status": "failed"}
                exit_code = 1
                print("Trace export failed; check Application Insights ingestion and RBAC.", file=sys.stderr)
            else:
                if exported != len(report["results"]):
                    report["status"] = "failed"
                    report["tracing"] = {"status": "failed", "spans": exported}
                    exit_code = 1
                    print("Trace count does not match the recorded model calls.", file=sys.stderr)
                else:
                    report["tracing"] = {"status": "exported", "spans": exported}
        elif args.trace:
            report["tracing"] = {"status": "failed"}
        for key in ("quality", "safety"):
            if report[key]["evaluation_status"] == "running":
                report[key]["evaluation_status"] = "failed"
        if "error_type" in report:
            report["status"] = "failed"
        report["ended_at"] = utc_now()
    try:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError:
        print(f"Cannot write monitoring report: {args.output}", file=sys.stderr)
        return 2
    print(f"Scenario 00a (lane a): {report['status']}. Report: {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
