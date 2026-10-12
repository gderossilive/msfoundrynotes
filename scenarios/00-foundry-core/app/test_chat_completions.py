import json
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import chat_completions


class LoadDeploymentTests(unittest.TestCase):
    @patch("chat_completions.subprocess.run")
    def test_loads_deployed_lane_outputs(self, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "FOUNDRY_SCENARIO_LANE_ID": "00a",
                    "AZURE_AI_ACCOUNT_NAME": "aifoundry123",
                    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-5-mini",
                    "AZURE_AI_PROJECT_NAME": "core-project",
                    "AZURE_RESOURCE_GROUP": "rg-foundry",
                    "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001",
                }
            ),
            stderr="",
        )

        deployment = chat_completions.load_deployment("dev")

        self.assertEqual(deployment.lane_id, "00a")
        self.assertEqual(deployment.account_name, "aifoundry123")
        self.assertEqual(deployment.model_deployment_name, "gpt-5-mini")
        self.assertEqual(deployment.resource_group, "rg-foundry")
        self.assertEqual(
            deployment.direct_base_url,
            "https://aifoundry123.services.ai.azure.com/openai/v1/",
        )
        self.assertEqual(
            deployment.project_base_url,
            "https://aifoundry123.services.ai.azure.com/api/projects/core-project/openai/v1/",
        )
        self.assertEqual(run.call_args.kwargs["cwd"], chat_completions.LANE_DIRECTORIES["00a"])

    @patch("chat_completions.subprocess.run")
    def test_loads_00c_gateway_output(self, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "FOUNDRY_SCENARIO_LANE_ID": "00c",
                    "AZURE_AI_ACCOUNT_NAME": "aifoundry123",
                    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-5-mini",
                    "AZURE_APIM_CHAT_COMPLETIONS_ENDPOINT": "https://apim123.azure-api.net/openai/v1/",
                }
            ),
            stderr="",
        )

        deployment = chat_completions.load_deployment("private", "00c")

        self.assertEqual(deployment.lane_id, "00c")
        self.assertEqual(run.call_args.kwargs["cwd"], chat_completions.LANE_DIRECTORIES["00c"])
        self.assertEqual(
            deployment.base_url("gateway"),
            "https://apim123.azure-api.net/openai/v1/",
        )

    @patch("chat_completions.subprocess.run")
    def test_rejects_an_environment_from_another_lane(self, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "FOUNDRY_SCENARIO_LANE_ID": "00c",
                    "AZURE_AI_ACCOUNT_NAME": "aifoundry123",
                    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-5-mini",
                }
            ),
            stderr="",
        )

        with self.assertRaisesRegex(chat_completions.ConfigurationError, "is not bound to lane 00a"):
            chat_completions.load_deployment("private")

    def test_rejects_an_unsupported_lane(self) -> None:
        with self.assertRaisesRegex(chat_completions.ConfigurationError, "00a or 00c"):
            chat_completions.load_deployment("private", "00b")

    def test_rejects_gateway_target_for_00a(self) -> None:
        deployment = chat_completions.Deployment("00a", "aifoundry123", "gpt-5-mini")

        with self.assertRaisesRegex(chat_completions.ConfigurationError, "does not expose"):
            deployment.base_url("gateway")

    def test_rejects_00c_without_a_gateway_endpoint(self) -> None:
        deployment = chat_completions.Deployment("00c", "aifoundry123", "gpt-5-mini")

        with self.assertRaisesRegex(chat_completions.ConfigurationError, "does not expose"):
            deployment.base_url("gateway")

    def test_requires_project_name_for_evaluation(self) -> None:
        deployment = chat_completions.Deployment("00a", "aifoundry123", "gpt-5-mini")
        with self.assertRaisesRegex(chat_completions.ConfigurationError, "AZURE_AI_PROJECT_NAME"):
            _ = deployment.project_base_url

    @patch("chat_completions.subprocess.run")
    def test_reports_azd_failure(self, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="environment not found",
        )

        with self.assertRaisesRegex(
            chat_completions.ConfigurationError,
            "environment not found",
        ):
            chat_completions.load_deployment("missing")


class CompletionTests(unittest.TestCase):
    def test_sends_one_user_message_and_returns_text(self) -> None:
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="  Hello from Foundry.  ")
                )
            ]
        )
        deployment = chat_completions.Deployment("00a", "aifoundry123", "gpt-5-mini")

        result = chat_completions.complete_prompt(client, deployment, "  Hello  ")

        self.assertEqual(result, "Hello from Foundry.")
        client.chat.completions.create.assert_called_once_with(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": "Hello"}],
        )

    def test_rejects_empty_prompt(self) -> None:
        with self.assertRaisesRegex(
            chat_completions.ConfigurationError,
            "Prompt must not be empty",
        ):
            chat_completions.complete_prompt(
                Mock(),
                chat_completions.Deployment("00a", "aifoundry123", "gpt-5-mini"),
                " ",
            )

    def test_rejects_empty_model_response(self) -> None:
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[])

        with self.assertRaisesRegex(RuntimeError, "no completion choices"):
            chat_completions.complete_prompt(
                client,
                chat_completions.Deployment("00a", "aifoundry123", "gpt-5-mini"),
                "Hello",
            )


class ClientTests(unittest.TestCase):
    def test_uses_azure_cli_credential(self) -> None:
        azure_identity = SimpleNamespace(
            AzureCliCredential=Mock(return_value="credential"),
            get_bearer_token_provider=Mock(return_value="token-provider"),
        )
        openai = SimpleNamespace(OpenAI=Mock(return_value="client"))

        with patch.dict(
            sys.modules,
            {
                "azure.identity": azure_identity,
                "openai": openai,
            },
        ):
            client = chat_completions.create_openai_client(
                "https://aifoundry123.services.ai.azure.com/openai/v1/"
            )

        azure_identity.AzureCliCredential.assert_called_once_with()
        azure_identity.get_bearer_token_provider.assert_called_once_with(
            "credential",
            chat_completions.TOKEN_SCOPE,
        )
        openai.OpenAI.assert_called_once_with(
            base_url="https://aifoundry123.services.ai.azure.com/openai/v1/",
            api_key="token-provider",
        )
        self.assertEqual(client, "client")

    def test_accepts_a_cognitive_services_token_scope(self) -> None:
        azure_identity = SimpleNamespace(
            AzureCliCredential=Mock(return_value="credential"),
            get_bearer_token_provider=Mock(return_value="token-provider"),
        )
        openai = SimpleNamespace(OpenAI=Mock(return_value="client"))

        with patch.dict(
            sys.modules,
            {
                "azure.identity": azure_identity,
                "openai": openai,
            },
        ):
            chat_completions.create_openai_client(
                "https://aifoundry123.openai.azure.com/openai/v1/",
                chat_completions.COGNITIVE_SERVICES_SCOPE,
            )

        azure_identity.get_bearer_token_provider.assert_called_once_with(
            "credential",
            chat_completions.COGNITIVE_SERVICES_SCOPE,
        )


class MainTests(unittest.TestCase):
    @patch("chat_completions.complete_prompt", return_value="Hello")
    @patch("chat_completions.create_openai_client")
    @patch("chat_completions.load_deployment")
    def test_main_prints_the_response(
        self,
        load_deployment: Mock,
        create_openai_client: Mock,
        complete_prompt: Mock,
    ) -> None:
        deployment = chat_completions.Deployment("00a", "aifoundry123", "gpt-5-mini")
        load_deployment.return_value = deployment

        with patch("builtins.print") as print_output:
            exit_code = chat_completions.main(
                ["--environment", "dev", "Say hello"]
            )

        self.assertEqual(exit_code, 0)
        load_deployment.assert_called_once_with("dev", "00a")
        create_openai_client.assert_called_once_with(deployment.direct_base_url)
        complete_prompt.assert_called_once_with(
            create_openai_client.return_value,
            deployment,
            "Say hello",
        )
        print_output.assert_called_once_with("Hello")

    @patch("chat_completions.complete_prompt", return_value="Hello")
    @patch("chat_completions.create_openai_client")
    @patch("chat_completions.load_deployment")
    def test_main_routes_00c_through_the_gateway(
        self,
        load_deployment: Mock,
        create_openai_client: Mock,
        complete_prompt: Mock,
    ) -> None:
        deployment = chat_completions.Deployment(
            "00c",
            "aifoundry123",
            "gpt-5-mini",
            "https://apim123.azure-api.net/openai/v1/",
        )
        load_deployment.return_value = deployment

        with patch("builtins.print"):
            exit_code = chat_completions.main(
                [
                    "--environment",
                    "private",
                    "--scenario",
                    "00c",
                    "--target",
                    "gateway",
                    "Say hello",
                ]
            )

        self.assertEqual(exit_code, 0)
        load_deployment.assert_called_once_with("private", "00c")
        create_openai_client.assert_called_once_with("https://apim123.azure-api.net/openai/v1/")


if __name__ == "__main__":
    unittest.main()
