#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from chat_completions import LANE_DIRECTORIES, ConfigurationError, load_deployment

GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,31}$")
RESOURCE_ID_PATTERN = re.compile(r"^/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[^/\s]+/providers/[^\s]+$")
LOG_ANALYTICS_RESOURCE = "https://api.loganalytics.io"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "usage-report.json"
KINDS = ("prompt", "completion", "reasoning", "total")
METRIC_KINDS = {
    "Prompt Tokens": "prompt",
    "Completion Tokens": "completion",
    "Completion Reasoning Tokens": "reasoning",
    "Total Tokens": "total",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def align_window(since: datetime, until: datetime) -> tuple[datetime, datetime]:
    # Platform metrics are per-minute buckets: use whole minutes for both sources so they cover the same traffic.
    aligned_since = since.replace(second=0, microsecond=0)
    aligned_until = until.replace(second=0, microsecond=0)
    if aligned_until < until:
        aligned_until += timedelta(minutes=1)
    return aligned_since, aligned_until


def parse_moment(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigurationError(f'"{value}" is not an ISO 8601 UTC timestamp.') from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_caller_labels(values: Sequence[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for value in values:
        label, separator, object_id = value.partition("=")
        if not separator or not LABEL_PATTERN.fullmatch(label) or not GUID_PATTERN.fullmatch(object_id):
            raise ConfigurationError("--caller must look like LABEL=<entra-object-id>.")
        labels[object_id.lower()] = label
    return labels


def run_az(arguments: list[str]) -> Any:
    try:
        result = subprocess.run(
            ["az", *arguments, "--output", "json"],
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ConfigurationError("Azure CLI (az) is required but was not found.") from exc
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no diagnostic output"
        raise RuntimeError(f"Azure CLI failed: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Azure CLI returned invalid JSON.") from exc


def read_environment_values(environment: str, lane_id: str = "00c") -> dict[str, Any]:
    result = subprocess.run(
        ["azd", "env", "get-values", "--environment", environment, "--output", "json"],
        cwd=LANE_DIRECTORIES[lane_id],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise ConfigurationError(f'Unable to read azd environment "{environment}".')
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("azd returned invalid JSON for the selected environment.") from exc
    if not isinstance(values, dict):
        raise ConfigurationError("azd environment values must be a JSON object.")
    return values


def build_usage_query(start: str, end: str) -> str:
    names = ", ".join(f'"{name}"' for name in METRIC_KINDS)
    return (
        "AppMetrics"
        f" | where TimeGenerated between (datetime({start}) .. datetime({end}))"
        f" | where Name in ({names})"
        ' | extend caller = tostring(Properties["Caller"])'
        ' | where caller != ""'
        " | summarize tokens = sum(Sum) by caller, metric = Name"
    )


def query_gateway_usage(workspace_customer_id: str, start: str, end: str) -> list[dict[str, Any]]:
    response = run_az(
        [
            "rest",
            "--method",
            "post",
            "--url",
            f"{LOG_ANALYTICS_RESOURCE}/v1/workspaces/{workspace_customer_id}/query",
            "--resource",
            LOG_ANALYTICS_RESOURCE,
            "--body",
            json.dumps({"query": build_usage_query(start, end)}),
        ]
    )
    tables = response.get("tables") if isinstance(response, dict) else None
    if not tables:
        return []
    columns = [column["name"] for column in tables[0]["columns"]]
    return [dict(zip(columns, row)) for row in tables[0]["rows"]]


def metric_kind(name: str) -> str | None:
    return METRIC_KINDS.get(name)


def aggregate_gateway_rows(rows: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, dict[str, int]]:
    usage: dict[str, dict[str, int]] = {}
    for row in rows:
        kind = metric_kind(str(row.get("metric", "")))
        caller = str(row.get("caller", "")).lower()
        if kind is None or not caller:
            continue
        label = labels.get(caller, f"unlabeled-{caller[:8]}")
        bucket = usage.setdefault(label, {name: 0 for name in KINDS})
        bucket[kind] += round(float(row.get("tokens") or 0))
    return usage


def query_model_tokens(account_id: str, deployment: str, start: str, end: str) -> dict[str, int]:
    response = run_az(
        [
            "monitor",
            "metrics",
            "list",
            "--resource",
            account_id,
            "--metrics",
            "InputTokens",
            "OutputTokens",
            "--filter",
            f"ModelDeploymentName eq '{deployment}'",
            "--aggregation",
            "Total",
            "--interval",
            "PT1M",
            "--start-time",
            start,
            "--end-time",
            end,
        ]
    )
    totals = {"input": 0, "output": 0}
    for metric in response.get("value", []):
        key = "input" if metric.get("name", {}).get("value") == "InputTokens" else "output"
        for series in metric.get("timeseries", []):
            for point in series.get("data", []):
                totals[key] += round(point.get("total") or 0)
    return totals


def estimate_cost(
    usage: dict[str, int], price_input_per_million: float | None, price_output_per_million: float | None
) -> float | None:
    # Reasoning tokens are already part of the completion count, so they are not added again.
    if price_input_per_million is None or price_output_per_million is None:
        return None
    return round(
        usage["prompt"] / 1_000_000 * price_input_per_million
        + usage["completion"] / 1_000_000 * price_output_per_million,
        6,
    )


def reconcile(
    gateway: dict[str, dict[str, int]],
    model_tokens: dict[str, int] | None,
    demo_totals: dict[str, int] | None,
) -> dict[str, Any]:
    gateway_prompt = sum(item["prompt"] for item in gateway.values())
    gateway_completion = sum(item["completion"] for item in gateway.values())
    result: dict[str, Any] = {
        "gateway_prompt": gateway_prompt,
        "gateway_completion": gateway_completion,
    }
    if model_tokens is not None:
        result["model_input"] = model_tokens["input"]
        result["model_output"] = model_tokens["output"]
        result["gateway_matches_model"] = (
            gateway_prompt == model_tokens["input"] and gateway_completion == model_tokens["output"]
        )
        # Positive values are tokens the model served that the gateway metric did not see.
        result["model_minus_gateway_input"] = model_tokens["input"] - gateway_prompt
        result["model_minus_gateway_output"] = model_tokens["output"] - gateway_completion
    if demo_totals is not None:
        mismatched = sorted(
            label
            for label in set(gateway) | set(demo_totals)
            if gateway.get(label, {}).get("total", 0) != demo_totals.get(label, 0)
        )
        result["response_headers_match_gateway"] = not mismatched
        result["response_header_mismatches"] = mismatched
    return result


def load_demo_totals(path: Path) -> dict[str, int]:
    report = json.loads(path.read_text(encoding="utf-8"))
    totals: dict[str, int] = {}
    for item in report.get("observations", []):
        if item.get("status") == 200 and isinstance(item.get("consumed_tokens"), int):
            totals[item["caller"]] = totals.get(item["caller"], 0) + item["consumed_tokens"]
    return totals


def build_report(
    gateway: dict[str, dict[str, int]],
    reconciliation: dict[str, Any],
    start: str,
    end: str,
    price_input_per_million: float | None,
    price_output_per_million: float | None,
) -> dict[str, Any]:
    callers = {
        label: {**usage, "estimated_cost": estimate_cost(usage, price_input_per_million, price_output_per_million)}
        for label, usage in sorted(gateway.items())
    }
    return {
        "window": {"start": start, "end": end},
        "callers": callers,
        "reconciliation": reconciliation,
        "cost_note": None
        if price_input_per_million is not None
        else "No prices were supplied, so no cost is estimated.",
    }


def print_summary(report: dict[str, Any]) -> None:
    print("caller        prompt  completion  reasoning  total  estimated cost")
    for label, usage in report["callers"].items():
        cost = "-" if usage["estimated_cost"] is None else f"{usage['estimated_cost']:.6f}"
        print(
            f"{label:<12}  {usage['prompt']:>6}  {usage['completion']:>10}  "
            f"{usage['reasoning']:>9}  {usage['total']:>5}  {cost}"
        )
    for key, value in report["reconciliation"].items():
        print(f"{key}: {value}")
    if report["cost_note"]:
        print(report["cost_note"])


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Report token usage per caller recorded by the 00c gateway and compare it with the "
            "model-side platform metrics."
        )
    )
    parser.add_argument("--environment", required=True, help="Name of the azd environment.")
    parser.add_argument(
        "--scenario",
        choices=("00a", "00c"),
        default="00c",
        help="Lane that owns the environment. Lane 00a needs its optional gateway. Defaults to 00c.",
    )
    parser.add_argument(
        "--caller",
        action="append",
        default=[],
        metavar="LABEL=OBJECT_ID",
        help="Readable label for a caller object ID. Repeat for each caller.",
    )
    parser.add_argument("--since", help="UTC start, ISO 8601. Defaults to one hour before --until.")
    parser.add_argument("--until", help="UTC end, ISO 8601. Defaults to now.")
    parser.add_argument(
        "--demo-report",
        type=Path,
        help="token-limit-results.json from token_limit_demo.py, to compare with response headers.",
    )
    parser.add_argument("--price-input-per-million", type=float, help="Your input price per million tokens.")
    parser.add_argument("--price-output-per-million", type=float, help="Your output price per million tokens.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Local JSON report path.")
    args = parser.parse_args(argv)
    for price in (args.price_input_per_million, args.price_output_per_million):
        if price is not None and price < 0:
            parser.error("Prices must not be negative.")
    if (args.price_input_per_million is None) != (args.price_output_per_million is None):
        parser.error("Provide both prices or neither.")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        labels = parse_caller_labels(args.caller)
        until = parse_moment(args.until) if args.until else utc_now()
        since = parse_moment(args.since) if args.since else until - timedelta(hours=1)
        if since >= until:
            raise ConfigurationError("--since must be earlier than --until.")
        since, until = align_window(since, until)
        start, end = iso(since), iso(until)

        deployment = load_deployment(args.environment, args.scenario)
        values = read_environment_values(args.environment, args.scenario)
        workspace = values.get("AZURE_USAGE_WORKSPACE_CUSTOMER_ID")
        account_id = values.get("AZURE_AI_ACCOUNT_ID")
        if not isinstance(workspace, str) or not GUID_PATTERN.fullmatch(workspace):
            raise ConfigurationError(
                "Usage metrics are not enabled: set AZURE_APIM_USAGE_METRICS=true and apply the 00c policy."
            )
        if not isinstance(account_id, str) or not RESOURCE_ID_PATTERN.fullmatch(account_id):
            raise ConfigurationError("The deployed lane is missing a valid AZURE_AI_ACCOUNT_ID.")

        gateway = aggregate_gateway_rows(query_gateway_usage(workspace, start, end), labels)
        if not gateway:
            print(
                "No gateway token metrics found yet. Ingestion can take several minutes; "
                "check the window and retry.",
                file=sys.stderr,
            )
            return 3
        model_tokens = query_model_tokens(account_id, deployment.model_deployment_name, start, end)
        demo_totals = load_demo_totals(args.demo_report) if args.demo_report else None
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"Report error: {exc}", file=sys.stderr)
        return 1

    report = build_report(
        gateway,
        reconcile(gateway, model_tokens, demo_totals),
        start,
        end,
        args.price_input_per_million,
        args.price_output_per_million,
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print_summary(report)
    if report["reconciliation"].get("gateway_matches_model") is False:
        print(
            "Gateway and model totals differ. The model counts every call to the deployment in whole-minute "
            "buckets: calls made in the same minutes without the gateway metric (for example before it was "
            "enabled, or bypassing the gateway) appear as a difference. Start the window after them.",
            file=sys.stderr,
        )
    checks = [
        value
        for key, value in report["reconciliation"].items()
        if key in ("gateway_matches_model", "response_headers_match_gateway")
    ]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
