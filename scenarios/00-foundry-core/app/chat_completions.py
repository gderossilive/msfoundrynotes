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
COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
LANE_DIRECTORIES = {
    "00a": Path(__file__).resolve().parent.parent / "00a-foundry-core-public",
    "00c": Path(__file__).resolve().parent.parent / "00c-foundry-core-byo-vnet",
}
ACCOUNT_PATTERN = re.compile(r"^[a-zA-Z0-9-]+$")
MODEL_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
GATEWAY_ENDPOINT_PATTERN = re.compile(
    r"^https://[a-zA-Z0-9-]+\.azure-api\.net/openai/v1/$"
)


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Deployment:
    lane_id: str
    account_name: str
    model_deployment_name: str
    gateway_endpoint: str | None = None
    project_name: str | None = None
    resource_group: str | None = None
    subscription_id: str | None = None

    @property
    def direct_base_url(self) -> str:
        return f"https://{self.account_name}.services.ai.azure.com/openai/v1/"

    @property
    def fine_tuning_base_url(self) -> str:
        return f"https://{self.account_name}.openai.azure.com/openai/v1/"

    @property
    def project_base_url(self) -> str:
        if self.lane_id != "00a" or not self.project_name:
            raise ConfigurationError("The 00a deployment is missing AZURE_AI_PROJECT_NAME for evaluation.")
        return (
            f"https://{self.account_name}.services.ai.azure.com/"
            f"api/projects/{self.project_name}/openai/v1/"
        )

    def base_url(self, target: str) -> str:
        if target == "direct":
            return self.direct_base_url
        if target == "gateway" and self.lane_id == "00c" and self.gateway_endpoint:
            return self.gateway_endpoint
        raise ConfigurationError(
            f'Lane {self.lane_id} does not expose a configured "{target}" target.'
        )


def load_deployment(environment_name: str, lane_id: str = "00a") -> Deployment:
    if lane_id not in LANE_DIRECTORIES:
        raise ConfigurationError("Lane must be 00a or 00c.")
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
            cwd=LANE_DIRECTORIES[lane_id],
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ConfigurationError("Azure Developer CLI (azd) is required but was not found.") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or "azd returned no diagnostic output"
        raise ConfigurationError(
            f'Unable to read azd environment "{environment_name}": {detail}'
        )

    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("azd returned invalid JSON for the selected environment.") from exc

    if not isinstance(values, dict):
        raise ConfigurationError("azd environment values must be a JSON object.")
    if values.get("FOUNDRY_SCENARIO_LANE_ID") != lane_id:
        raise ConfigurationError(
            f'azd environment "{environment_name}" is not bound to lane {lane_id}.'
        )

    account_name = values.get("AZURE_AI_ACCOUNT_NAME")
    model_deployment_name = values.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    if not isinstance(account_name, str) or not ACCOUNT_PATTERN.fullmatch(account_name):
        raise ConfigurationError("The deployed lane is missing a valid AZURE_AI_ACCOUNT_NAME.")
    if (
        not isinstance(model_deployment_name, str)
        or not MODEL_PATTERN.fullmatch(model_deployment_name)
    ):
        raise ConfigurationError(
            "The deployed lane is missing a valid AZURE_AI_MODEL_DEPLOYMENT_NAME."
        )

    gateway_endpoint = values.get("AZURE_APIM_CHAT_COMPLETIONS_ENDPOINT")
    project_name = values.get("AZURE_AI_PROJECT_NAME")
    resource_group = values.get("AZURE_RESOURCE_GROUP")
    subscription_id = values.get("AZURE_SUBSCRIPTION_ID")
    if project_name is not None and (
        not isinstance(project_name, str) or not MODEL_PATTERN.fullmatch(project_name)
    ):
        raise ConfigurationError("The deployed lane has an invalid AZURE_AI_PROJECT_NAME.")
    if lane_id == "00a" and (
        not isinstance(resource_group, str)
        or not resource_group.strip()
        or not isinstance(subscription_id, str)
        or not subscription_id.strip()
    ):
        raise ConfigurationError(
            "The deployed 00a lane is missing AZURE_RESOURCE_GROUP or AZURE_SUBSCRIPTION_ID."
        )
    if lane_id == "00c":
        if not isinstance(gateway_endpoint, str) or not GATEWAY_ENDPOINT_PATTERN.fullmatch(
            gateway_endpoint
        ):
            raise ConfigurationError(
                "The deployed 00c lane is missing a valid AZURE_APIM_CHAT_COMPLETIONS_ENDPOINT."
            )
    elif gateway_endpoint is not None:
        raise ConfigurationError(
            "The public lane 00a must not expose an API Management gateway endpoint."
        )

    return Deployment(
        lane_id,
        account_name,
        model_deployment_name,
        gateway_endpoint,
        project_name,
        resource_group,
        subscription_id,
    )


def create_openai_client(base_url: str, token_scope: str = TOKEN_SCOPE) -> Any:
    from azure.identity import AzureCliCredential, get_bearer_token_provider
    from openai import OpenAI

    token_provider = get_bearer_token_provider(
        AzureCliCredential(),
        token_scope,
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
        description="Send one prompt to the model deployed by Foundry Core scenario 00a or 00c."
    )
    parser.add_argument(
        "--environment",
        required=True,
        help="Name of the provisioned scenario 00a or 00c azd environment.",
    )
    parser.add_argument(
        "--scenario",
        choices=tuple(LANE_DIRECTORIES),
        default="00a",
        help="Foundry Core scenario that owns the azd environment. Defaults to 00a.",
    )
    parser.add_argument(
        "--target",
        choices=("direct", "gateway"),
        default="direct",
        help="Endpoint to call. Gateway is available only for lane 00c after its APIM policy is applied.",
    )
    parser.add_argument("prompt", help="Single prompt to send to the deployed model.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        deployment = load_deployment(args.environment, args.scenario)
        client = create_openai_client(deployment.base_url(args.target))
        print(complete_prompt(client, deployment, args.prompt))
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except request_error_types() as exc:
        print(f"Request error for {args.target} target: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
