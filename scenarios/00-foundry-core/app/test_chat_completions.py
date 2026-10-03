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
                }
            ),
            stderr="",
        )

        deployment = chat_completions.load_deployment("dev")

        self.assertEqual(deployment.account_name, "aifoundry123")
        self.assertEqual(deployment.model_deployment_name, "gpt-5-mini")
        self.assertEqual(
            deployment.base_url,
            "https://aifoundry123.services.ai.azure.com/openai/v1/",
        )
        self.assertEqual(run.call_args.kwargs["cwd"], chat_completions.LANE_DIRECTORY)

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

        with self.assertRaisesRegex(
            chat_completions.ConfigurationError,
            "is not bound to lane 00a",
        ):
            chat_completions.load_deployment("private")

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

    @patch("chat_completions.subprocess.run")
    def test_rejects_invalid_json(self, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="{",
            stderr="",
        )

        with self.assertRaisesRegex(
            chat_completions.ConfigurationError,
            "invalid JSON",
        ):
            chat_completions.load_deployment("dev")

    @patch("chat_completions.subprocess.run")
    def test_rejects_invalid_account_name(self, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "FOUNDRY_SCENARIO_LANE_ID": "00a",
                    "AZURE_AI_ACCOUNT_NAME": "invalid.account",
                    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-5-mini",
                }
            ),
            stderr="",
        )

        with self.assertRaisesRegex(
            chat_completions.ConfigurationError,
            "AZURE_AI_ACCOUNT_NAME",
        ):
            chat_completions.load_deployment("dev")


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
        deployment = chat_completions.Deployment(
            "aifoundry123",
            "gpt-5-mini",
        )

        result = chat_completions.complete_prompt(
            client,
            deployment,
            "  Hello  ",
        )

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
                chat_completions.Deployment("aifoundry123", "gpt-5-mini"),
                " ",
            )

    def test_rejects_empty_model_choices(self) -> None:
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[])

        with self.assertRaisesRegex(RuntimeError, "no completion choices"):
            chat_completions.complete_prompt(
                client,
                chat_completions.Deployment(
                    "aifoundry123",
                    "gpt-5-mini",
                ),
                "Hello",
            )

    def test_rejects_empty_model_text(self) -> None:
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=" "),
                )
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "empty text response"):
            chat_completions.complete_prompt(
                client,
                chat_completions.Deployment(
                    "aifoundry123",
                    "gpt-5-mini",
                ),
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
            base_url=(
                "https://aifoundry123.services.ai.azure.com/openai/v1/"
            ),
            api_key="token-provider",
        )
        self.assertEqual(client, "client")


class MainTests(unittest.TestCase):
    @patch("chat_completions.complete_prompt", return_value="Hello")
    @patch("chat_completions.create_openai_client", return_value="client")
    @patch("chat_completions.load_deployment")
    def test_prints_completion(
        self,
        load_deployment: Mock,
        create_client: Mock,
        complete_prompt: Mock,
    ) -> None:
        deployment = chat_completions.Deployment(
            "aifoundry123",
            "gpt-5-mini",
        )
        load_deployment.return_value = deployment

        with patch("builtins.print") as print_mock:
            result = chat_completions.main(
                ["--environment", "dev", "Hello"]
            )

        self.assertEqual(result, 0)
        create_client.assert_called_once_with(deployment.base_url)
        complete_prompt.assert_called_once_with(
            "client",
            deployment,
            "Hello",
        )
        print_mock.assert_called_once_with("Hello")

    @patch(
        "chat_completions.load_deployment",
        side_effect=chat_completions.ConfigurationError("bad environment"),
    )
    def test_returns_two_for_configuration_error(
        self,
        load_deployment: Mock,
    ) -> None:
        with patch("builtins.print") as print_mock:
            result = chat_completions.main(
                ["--environment", "dev", "Hello"]
            )

        self.assertEqual(result, 2)
        load_deployment.assert_called_once_with("dev")
        self.assertEqual(print_mock.call_args.kwargs["file"], sys.stderr)


if __name__ == "__main__":
    unittest.main()
