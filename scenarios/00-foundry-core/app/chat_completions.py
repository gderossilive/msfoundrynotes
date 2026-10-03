#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

TOKEN_SCOPE = "https://ai.azure.com/.default"
LANE_DIRECTORY = (
    Path(__file__).resolve().parent.parent / "00a-foundry-core-public"
)
ACCOUNT_PATTERN = re.compile(r"^[a-zA-Z0-9-]+$")
MODEL_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Deployment:
    account_name: str
    model_deployment_name: str

    @property
    def base_url(self) -> str:
        return f"https://{self.account_name}.services.ai.azure.com/openai/v1/"


def load_deployment(environment_name: str) -> Deployment:
    try:
        result = subprocess.run(
            [
                "azd",
                "env",
                "get-values",
                "--environment",
                environment_name,
                "--output",
                "json",
            ],
            cwd=LANE_DIRECTORY,
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ConfigurationError(
            "Azure Developer CLI (azd) is required but was not found."
        ) from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or "azd returned no diagnostic output"
        raise ConfigurationError(
            f'Unable to read azd environment "{environment_name}": {detail}'
        )

    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            "azd returned invalid JSON for the selected environment."
        ) from exc

    if not isinstance(values, dict):
        raise ConfigurationError("azd environment values must be a JSON object.")
    if values.get("FOUNDRY_SCENARIO_LANE_ID") != "00a":
        raise ConfigurationError(
            f'azd environment "{environment_name}" is not bound to lane 00a.'
        )

    account_name = values.get("AZURE_AI_ACCOUNT_NAME")
    model_deployment_name = values.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    if not isinstance(account_name, str) or not ACCOUNT_PATTERN.fullmatch(
        account_name
    ):
        raise ConfigurationError(
            "The deployed lane is missing a valid AZURE_AI_ACCOUNT_NAME."
        )
    if (
        not isinstance(model_deployment_name, str)
        or not MODEL_PATTERN.fullmatch(model_deployment_name)
    ):
        raise ConfigurationError(
            "The deployed lane is missing a valid "
            "AZURE_AI_MODEL_DEPLOYMENT_NAME."
        )

    return Deployment(account_name, model_deployment_name)


def create_openai_client(base_url: str) -> Any:
    from azure.identity import AzureCliCredential, get_bearer_token_provider
    from openai import OpenAI

    token_provider = get_bearer_token_provider(
        AzureCliCredential(),
        TOKEN_SCOPE,
    )
    return OpenAI(base_url=base_url, api_key=token_provider)


def request_error_types() -> tuple[type[BaseException], type[BaseException]]:
    from openai import APIConnectionError, APIStatusError

    return APIConnectionError, APIStatusError


def complete_prompt(client: Any, deployment: Deployment, prompt: str) -> str:
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ConfigurationError("Prompt must not be empty.")

    completion = client.chat.completions.create(
        model=deployment.model_deployment_name,
        messages=[{"role": "user", "content": normalized_prompt}],
    )
    if not completion.choices:
        raise RuntimeError("The model returned no completion choices.")

    content = completion.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("The model returned an empty text response.")
    return content.strip()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send one prompt to the model deployed by Foundry Core 00a."
    )
    parser.add_argument(
        "--environment",
        required=True,
        help="Name of the provisioned scenario 00a azd environment.",
    )
    parser.add_argument(
        "prompt",
        help="Single prompt to send to the deployed model.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        deployment = load_deployment(args.environment)
        client = create_openai_client(deployment.base_url)
        print(complete_prompt(client, deployment, args.prompt))
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except request_error_types() as exc:
        print(f"Request error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
