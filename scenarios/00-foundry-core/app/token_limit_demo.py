#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from chat_completions import TOKEN_SCOPE, ConfigurationError, load_deployment

PROMPT = "Reply with one word: ready."
MAX_COMPLETION_TOKENS = 64
CONSUMED_HEADER = "x-foundrylab-consumed-tokens"
REMAINING_HEADER = "x-foundrylab-remaining-tokens"
DEFAULT_RETRY_AFTER_SECONDS = 60
MAX_RETRY_WAIT_SECONDS = 90
DEFAULT_MAX_CALLS = 15
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "token-limit-results.json"


@dataclass(frozen=True)
class Observation:
    caller: str
    status: int
    consumed_tokens: int | None
    remaining_tokens: int | None
    retry_after_seconds: int | None
    elapsed_ms: int
    started_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def header_int(headers: Any, name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def az_token_provider(config_dir: Path | None) -> Callable[[], str]:
    environment = dict(os.environ)
    if config_dir is not None:
        environment["AZURE_CONFIG_DIR"] = str(config_dir)

    def provider() -> str:
        result = subprocess.run(
            [
                "az",
                "account",
                "get-access-token",
                "--scope",
                TOKEN_SCOPE,
                "--query",
                "accessToken",
                "--output",
                "tsv",
            ],
            capture_output=True,
            check=False,
            text=True,
            env=environment,
        )
        token = result.stdout.strip()
        if result.returncode != 0 or not token:
            raise ConfigurationError(
                "Unable to acquire a Microsoft Entra token for the selected caller."
            )
        return token

    return provider


def create_client(base_url: str, token_provider: Callable[[], str]) -> Any:
    from openai import OpenAI

    # Automatic retries would hide the 429 that this demonstration is about.
    return OpenAI(base_url=base_url, api_key=token_provider, max_retries=0)


def send_request(client: Any, model: str, caller: str) -> Observation:
    started_at = utc_now()
    started = time.monotonic()
    try:
        response = client.chat.completions.with_raw_response.create(
            model=model,
            messages=[{"role": "user", "content": PROMPT}],
            max_completion_tokens=MAX_COMPLETION_TOKENS,
        )
        status, headers = response.status_code, response.headers
    except Exception as exc:
        failed_response = getattr(exc, "response", None)
        status = getattr(exc, "status_code", None)
        if not isinstance(status, int) or failed_response is None:
            raise
        headers = failed_response.headers
    return Observation(
        caller=caller,
        status=status,
        consumed_tokens=header_int(headers, CONSUMED_HEADER),
        remaining_tokens=header_int(headers, REMAINING_HEADER),
        retry_after_seconds=header_int(headers, "retry-after"),
        elapsed_ms=round((time.monotonic() - started) * 1000),
        started_at=started_at,
    )


def retry_wait_seconds(retry_after: int | None) -> int:
    seconds = retry_after if retry_after and retry_after > 0 else DEFAULT_RETRY_AFTER_SECONDS
    return min(seconds, MAX_RETRY_WAIT_SECONDS) + 1


def run_demo(
    send_a: Callable[[], Observation],
    send_b: Callable[[], Observation],
    sleep: Callable[[float], None],
    max_calls: int,
) -> dict[str, Any]:
    observations: list[Observation] = []
    limit_hit: Observation | None = None

    for _ in range(max_calls):
        observation = send_a()
        observations.append(observation)
        if observation.status == 429:
            limit_hit = observation
            break
        if observation.status != 200:
            break

    verdict = {
        "limit_enforced": limit_hit is not None,
        "caller_b_unaffected": None,
        "caller_a_recovered": None,
    }
    waited_seconds = None

    if limit_hit is not None:
        other = send_b()
        observations.append(other)
        verdict["caller_b_unaffected"] = other.status == 200

        waited_seconds = retry_wait_seconds(limit_hit.retry_after_seconds)
        sleep(waited_seconds)
        recovery = send_a()
        observations.append(recovery)
        verdict["caller_a_recovered"] = recovery.status == 200

    return {
        "observations": [asdict(item) for item in observations],
        "waited_seconds": waited_seconds,
        "verdict": verdict,
        "passed": all(value is True for value in verdict.values()),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Show the per-caller token limit of the gateway in scenario 00c, or in 00a with its optional gateway: caller A reaches the limit, "
            "caller B is unaffected, and caller A recovers after Retry-After."
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
        "--caller-b-config-dir",
        required=True,
        type=Path,
        help="Azure CLI configuration directory already signed in as the second caller.",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=DEFAULT_MAX_CALLS,
        help=f"Upper bound for caller A requests before giving up. Defaults to {DEFAULT_MAX_CALLS}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Local JSON report. It contains statuses and counters, never prompts or tokens.",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.max_calls <= 50:
        parser.error("--max-calls must be between 1 and 50.")
    return args


def print_summary(report: dict[str, Any]) -> None:
    print("caller  status  consumed  remaining  retry-after")
    for item in report["observations"]:
        cells = [
            item["caller"],
            str(item["status"]),
            str(item["consumed_tokens"]),
            str(item["remaining_tokens"]),
            str(item["retry_after_seconds"]),
        ]
        print("  ".join(cell.ljust(width) for cell, width in zip(cells, (6, 6, 8, 9, 11))))
    for name, value in report["verdict"].items():
        print(f"{name}: {value}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        deployment = load_deployment(args.environment, args.scenario)
        if not args.caller_b_config_dir.is_dir():
            raise ConfigurationError("The second caller's Azure CLI configuration directory is missing.")
        base_url = deployment.base_url("gateway")
        client_a = create_client(base_url, az_token_provider(None))
        client_b = create_client(base_url, az_token_provider(args.caller_b_config_dir))
        model = deployment.model_deployment_name
        report = run_demo(
            lambda: send_request(client_a, model, "A"),
            lambda: send_request(client_b, model, "B"),
            time.sleep,
            args.max_calls,
        )
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Request error for gateway target: {type(exc).__name__}", file=sys.stderr)
        return 1

    report = {"generated_at": utc_now(), "environment": args.environment, **report}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print_summary(report)
    if not report["verdict"]["limit_enforced"]:
        print(
            "The limit was not reached. Set AZURE_APIM_TOKENS_PER_MINUTE, apply the gateway policy "
            "again, or raise --max-calls.",
            file=sys.stderr,
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
