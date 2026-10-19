#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from benchmark_documents import (
    FIELDS,
    SYSTEM_PROMPT,
    Document,
    classify_document,
    collect_predictions,
    load_documents,
    response_format,
    run_foundry_evaluation,
)
from chat_completions import (
    COGNITIVE_SERVICES_SCOPE,
    ConfigurationError,
    Deployment,
    create_openai_client,
    load_deployment,
    request_error_types,
)
from prepare_finetuning_data import DEFAULT_OUTPUT_DIR, prepare

BASE_MODEL = "gpt-4.1-mini-2025-04-14"
TRAINING_TYPE = "Developer"
TRAINING_TYPE_WIRE = "developerTier"
FINE_TUNING_API_VERSION = "2025-05-15-preview"
N_EPOCHS = 3
LEARNING_RATE_MULTIPLIER = 0.5
SEED = 41
SUFFIX = "docs-00a-v1"
DEFAULT_STATE = Path(__file__).resolve().parent / "fine-tuning-state.json"
DEFAULT_FINAL_REPORT = Path(__file__).resolve().parent / "fine-tuning-final-results.json"
DEFAULT_DEPLOYMENT_NAME = "gpt-4.1-mini-docs-ft"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot read fine-tuning state {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise ConfigurationError("Fine-tuning state must be a JSON object.")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def fine_tuning_request(
    deployment: Deployment,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import requests
    from azure.identity import AzureCliCredential

    if not deployment.project_name:
        raise ConfigurationError("The 00a deployment is missing its Foundry project name.")
    token = AzureCliCredential().get_token("https://ai.azure.com/.default").token
    url = (
        f"https://{deployment.account_name}.services.ai.azure.com/api/projects/"
        f"{deployment.project_name}/fine_tuning/{path}"
    )
    # The current preview endpoint requires this binder parameter for job operations.
    response = requests.request(
        method,
        url,
        params={
            "api-version": FINE_TUNING_API_VERSION,
            "fineTuningJob": "supervised",
        },
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Foundry fine-tuning request failed ({response.status_code}): {response.text}"
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError("Foundry fine-tuning response was not JSON.") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Foundry fine-tuning response must be a JSON object.")
    return result


def load_sft_documents(path: Path) -> list[Document]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ConfigurationError(f"Cannot read SFT dataset {path}: {exc}") from exc
    documents = []
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            messages = item["messages"]
            system, user, assistant = messages
            expected = json.loads(assistant["content"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError(f"Invalid SFT example at line {index} in {path}.") from exc
        if (
            len(messages) != 3
            or system != {"role": "system", "content": SYSTEM_PROMPT}
            or user.get("role") != "user"
            or not isinstance(user.get("content"), str)
            or assistant.get("role") != "assistant"
            or not isinstance(expected, dict)
            or set(expected) != set(FIELDS)
            or not all(isinstance(expected[field], str) for field in FIELDS)
        ):
            raise ConfigurationError(f"SFT example at line {index} does not match the benchmark contract.")
        documents.append(Document(index, user["content"], expected))
    if not documents:
        raise ConfigurationError(f"SFT dataset {path} is empty.")
    return documents


def submit_job(
    environment: str,
    state_path: Path,
    data_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    state = load_state(state_path)
    if state.get("job_id"):
        raise ConfigurationError(
            f"State already contains job {state['job_id']}; use a new state file for another run."
        )
    manifest = prepare(data_dir)
    deployment = load_deployment(environment, "00a")
    client = create_openai_client(deployment.fine_tuning_base_url, COGNITIVE_SERVICES_SCOPE)
    if state.get("training_file_id") and state.get("validation_file_id"):
        training_file_id = state["training_file_id"]
        validation_file_id = state["validation_file_id"]
    else:
        with (data_dir / "training.jsonl").open("rb") as training_stream:
            training_file = client.files.create(file=training_stream, purpose="fine-tune")
        with (data_dir / "validation.jsonl").open("rb") as validation_stream:
            validation_file = client.files.create(file=validation_stream, purpose="fine-tune")
        training_file_id = training_file.id
        validation_file_id = validation_file.id
        state = {
            "environment": environment,
            "account_name": deployment.account_name,
            "project_name": deployment.project_name,
            "resource_group": deployment.resource_group,
            "subscription_id": deployment.subscription_id,
            "base_deployment": deployment.model_deployment_name,
            "base_model": BASE_MODEL,
            "training_type": TRAINING_TYPE,
            "n_epochs": N_EPOCHS,
            "learning_rate_multiplier": LEARNING_RATE_MULTIPLIER,
            "seed": SEED,
            "suffix": SUFFIX,
            "manifest": manifest,
            "training_file_id": training_file_id,
            "validation_file_id": validation_file_id,
            "temporary_deployments": [],
            "checkpoint_evaluations": [],
        }
        save_state(state_path, state)
    job = fine_tuning_request(
        deployment,
        "POST",
        "jobs",
        {
            "model": BASE_MODEL,
            "training_file": training_file_id,
            "validation_file": validation_file_id,
            "seed": SEED,
            "suffix": SUFFIX,
            "method": {
                "type": "supervised",
                "supervised": {
                    "hyperparameters": {
                        "n_epochs": N_EPOCHS,
                        "learning_rate_multiplier": LEARNING_RATE_MULTIPLIER,
                    }
                },
            },
            "trainingType": TRAINING_TYPE_WIRE,
        },
    )
    state["job_id"] = job["id"]
    state["job_status"] = job["status"]
    state["training_type_wire"] = TRAINING_TYPE_WIRE
    save_state(state_path, state)
    return state


def monitor_job(
    state_path: Path, poll_seconds: int = 60, timeout_seconds: int = 21600
) -> dict[str, Any]:
    state = load_state(state_path)
    job_id = state.get("job_id")
    environment = state.get("environment")
    if not isinstance(job_id, str) or not isinstance(environment, str):
        raise ConfigurationError("State does not contain a submitted fine-tuning job.")
    deployment = load_deployment(environment, "00a")
    deadline = time.monotonic() + timeout_seconds
    while True:
        job = fine_tuning_request(deployment, "GET", f"jobs/{job_id}")
        state["job_status"] = job["status"]
        save_state(state_path, state)
        if job["status"] in ("succeeded", "failed", "cancelled"):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Fine-tuning job {job_id} did not finish within the configured timeout.")
        time.sleep(poll_seconds)
    if job["status"] != "succeeded":
        raise RuntimeError(
            f"Fine-tuning job {job_id} ended with {job['status']}: {job.get('error')}"
        )

    checkpoint_response = fine_tuning_request(
        deployment, "GET", f"jobs/{job_id}/checkpoints"
    )
    checkpoints = checkpoint_response.get("data")
    if not isinstance(checkpoints, list):
        raise RuntimeError(f"Checkpoint response for {job_id} is missing its data array.")
    if len(checkpoints) != N_EPOCHS:
        raise RuntimeError(f"Expected {N_EPOCHS} checkpoints for {job_id}, received {len(checkpoints)}.")
    state["fine_tuned_model"] = job.get("fine_tuned_model")
    state["result_files"] = list(job.get("result_files") or [])
    state["checkpoints"] = sorted(checkpoints, key=lambda item: item.get("step_number", 0))
    save_state(state_path, state)
    return state


def run_az(arguments: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["az", *arguments, "--output", "json", "--only-show-errors"],
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ConfigurationError("Azure CLI is required but was not found.") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Azure CLI returned no details"
        raise RuntimeError(f"Azure CLI command failed: {detail}")
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Azure CLI returned invalid JSON.") from exc


def deploy_checkpoint(
    deployment: Deployment,
    deployment_name: str,
    model_name: str,
    sku_name: str,
    capacity: int,
) -> None:
    if not deployment.resource_group or not deployment.subscription_id:
        raise ConfigurationError("Deployment context is missing resource group or subscription.")
    run_az(
        [
            "cognitiveservices",
            "account",
            "deployment",
            "create",
            "--subscription",
            deployment.subscription_id,
            "--resource-group",
            deployment.resource_group,
            "--name",
            deployment.account_name,
            "--deployment-name",
            deployment_name,
            "--model-name",
            model_name,
            "--model-version",
            "1",
            "--model-format",
            "OpenAI",
            "--sku-name",
            sku_name,
            "--sku-capacity",
            str(capacity),
        ]
    )


def delete_checkpoint_deployment(deployment: Deployment, deployment_name: str) -> None:
    if not deployment.resource_group or not deployment.subscription_id:
        raise ConfigurationError("Deployment context is missing resource group or subscription.")
    run_az(
        [
            "cognitiveservices",
            "account",
            "deployment",
            "delete",
            "--subscription",
            deployment.subscription_id,
            "--resource-group",
            deployment.resource_group,
            "--name",
            deployment.account_name,
            "--deployment-name",
            deployment_name,
        ]
    )


def evaluate_model(
    deployment: Deployment, deployment_name: str, documents: list[Document]
) -> dict[str, Any]:
    model_client = create_openai_client(deployment.direct_base_url)
    results, rows = collect_predictions(model_client, deployment_name, documents)
    evaluation_client = create_openai_client(deployment.project_base_url)
    evaluation = run_foundry_evaluation(evaluation_client, rows)
    return {
        "model": deployment_name,
        "sample_size": len(documents),
        "valid_responses": len(rows),
        "errors": len(documents) - len(rows),
        "coverage": len(rows) / len(documents),
        **evaluation,
        "results": results,
    }


def wait_for_deployment(
    deployment: Deployment,
    deployment_name: str,
    document: Document,
    attempts: int = 10,
    delay_seconds: int = 30,
) -> None:
    client = create_openai_client(deployment.direct_base_url)
    schema = response_format([document])
    for attempt in range(1, attempts + 1):
        try:
            classify_document(client, deployment_name, document, schema)
            return
        except request_error_types() as exc:
            if attempt == attempts:
                raise RuntimeError(
                    f"Deployment {deployment_name} was not ready after {attempts} attempts: {exc}"
                ) from exc
            time.sleep(delay_seconds)


def validation_rank(evaluation: dict[str, Any]) -> tuple[float, float, float, float]:
    accuracy = evaluation["report"]["accuracy"]
    valid_loss = evaluation.get("valid_loss")
    return (
        accuracy["all_fields"],
        accuracy["priority"],
        evaluation["report"]["coverage"],
        -valid_loss if isinstance(valid_loss, (int, float)) else float("-inf"),
    )


def checkpoint_model_id(checkpoint: dict[str, Any]) -> str:
    for key in ("fine_tuned_model_checkpoint", "fine_tuned_model"):
        value = checkpoint.get(key)
        if isinstance(value, str) and value:
            return value
    raise ConfigurationError("Checkpoint is missing its fine-tuned model ID.")


def checkpoint_valid_loss(checkpoint: dict[str, Any]) -> float | None:
    metrics = checkpoint.get("metrics")
    if not isinstance(metrics, dict):
        return None
    for key in ("full_valid_loss", "valid_loss"):
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def evaluate_checkpoints(
    state_path: Path,
    deployment_name: str = DEFAULT_DEPLOYMENT_NAME,
    sku_name: str = "GlobalStandard",
    capacity: int = 10,
) -> dict[str, Any]:
    state = load_state(state_path)
    if state.get("job_status") != "succeeded" or not isinstance(state.get("checkpoints"), list):
        raise ConfigurationError("Fine-tuning job has not completed successfully.")
    environment = state.get("environment")
    if not isinstance(environment, str):
        raise ConfigurationError("State is missing its azd environment.")
    deployment = load_deployment(environment, "00a")
    validation_documents = load_sft_documents(DEFAULT_OUTPUT_DIR / "validation.jsonl")
    evaluations: list[dict[str, Any]] = []
    evaluations.extend(state.get("checkpoint_evaluations") or [])

    for ordinal, checkpoint in enumerate(state["checkpoints"], start=1):
        model_id = checkpoint_model_id(checkpoint)
        if any(evaluation.get("checkpoint") == model_id for evaluation in evaluations):
            continue
        temporary_name = f"docs-ft-{state['job_id'][-6:]}-cp{ordinal}"
        if temporary_name not in state["temporary_deployments"]:
            deploy_checkpoint(
                deployment,
                temporary_name,
                model_id,
                sku_name,
                capacity,
            )
            state["temporary_deployments"].append(temporary_name)
            save_state(state_path, state)
        wait_for_deployment(deployment, temporary_name, validation_documents[0])
        report = evaluate_model(deployment, temporary_name, validation_documents)
        evaluations.append(
            {
                "checkpoint": model_id,
                "step_number": checkpoint.get("step_number"),
                "valid_loss": checkpoint_valid_loss(checkpoint),
                "temporary_deployment": temporary_name,
                "report": report,
            }
        )
        state["checkpoint_evaluations"] = evaluations
        save_state(state_path, state)

    winner = max(evaluations, key=validation_rank)
    deploy_checkpoint(
        deployment,
        deployment_name,
        winner["checkpoint"],
        sku_name,
        capacity,
    )
    state["selected_checkpoint"] = winner["checkpoint"]
    state["selected_checkpoint_step"] = winner["step_number"]
    state["selected_validation_report"] = winner["report"]
    state["final_deployment"] = deployment_name
    save_state(state_path, state)

    for temporary_name in list(state["temporary_deployments"]):
        delete_checkpoint_deployment(deployment, temporary_name)
        state["temporary_deployments"].remove(temporary_name)
        save_state(state_path, state)
    return state


def final_test(state_path: Path, output: Path = DEFAULT_FINAL_REPORT) -> dict[str, Any]:
    state = load_state(state_path)
    environment = state.get("environment")
    deployment_name = state.get("final_deployment")
    if not isinstance(environment, str) or not isinstance(deployment_name, str):
        raise ConfigurationError("State does not contain a selected deployed checkpoint.")
    deployment = load_deployment(environment, "00a")
    documents = load_documents()
    wait_for_deployment(deployment, deployment_name, documents[0])
    report = evaluate_model(deployment, deployment_name, documents)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    state["final_test_report"] = str(output)
    state["final_test"] = {
        key: report[key]
        for key in (
            "model",
            "sample_size",
            "valid_responses",
            "errors",
            "coverage",
            "evaluation_id",
            "run_id",
            "report_url",
            "accuracy",
        )
    }
    save_state(state_path, state)
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune scenario 00a document classification.")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--force", action="store_true")
    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("--environment", required=True)
    monitor_parser = subparsers.add_parser("monitor")
    monitor_parser.add_argument("--poll-seconds", type=int, default=60)
    monitor_parser.add_argument("--timeout-seconds", type=int, default=21600)
    evaluate_parser = subparsers.add_parser("evaluate-checkpoints")
    evaluate_parser.add_argument("--deployment-name", default=DEFAULT_DEPLOYMENT_NAME)
    evaluate_parser.add_argument("--sku-name", default="GlobalStandard")
    evaluate_parser.add_argument("--capacity", type=int, default=10)
    final_parser = subparsers.add_parser("final-test")
    final_parser.add_argument("--output", type=Path, default=DEFAULT_FINAL_REPORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(DEFAULT_OUTPUT_DIR, args.force)
        elif args.command == "submit":
            result = submit_job(args.environment, args.state)
        elif args.command == "monitor":
            result = monitor_job(args.state, args.poll_seconds, args.timeout_seconds)
        elif args.command == "evaluate-checkpoints":
            result = evaluate_checkpoints(
                args.state, args.deployment_name, args.sku_name, args.capacity
            )
        else:
            result = final_test(args.state, args.output)
    except ConfigurationError as exc:
        print(f"Fine-tuning configuration error: {exc}", file=sys.stderr)
        return 2
    except request_error_types() as exc:
        print(f"Foundry request error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Fine-tuning error: {exc}", file=sys.stderr)
        return 1
    if args.command == "prepare":
        print(f"Prepared {result['training_rows']}/{result['validation_rows']} examples.")
    elif args.command == "final-test":
        print(json.dumps(result["accuracy"], indent=2))
    else:
        print(f"State: {args.state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
