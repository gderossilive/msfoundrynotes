import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import fine_tune_documents as fine_tune
from chat_completions import ConfigurationError, Deployment
from prepare_finetuning_data import prepare


class FineTuningContractTests(unittest.TestCase):
    def test_loads_validation_as_benchmark_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            prepare(output_dir)
            documents = fine_tune.load_sft_documents(output_dir / "validation.jsonl")

        self.assertEqual(len(documents), 12)
        self.assertEqual(documents[0].index, 1)
        self.assertEqual(set(documents[0].expected), set(fine_tune.FIELDS))

    def test_rejects_sft_prompt_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "validation.jsonl"
            path.write_text(json.dumps({
                "messages": [
                    {"role": "system", "content": "different"},
                    {"role": "user", "content": "document"},
                    {"role": "assistant", "content": json.dumps({
                        "document_type": "Invoice",
                        "department": "Accounting",
                        "priority": "Medium",
                    })},
                ]
            }), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "benchmark contract"):
                fine_tune.load_sft_documents(path)

    def test_validation_rank_uses_requested_tie_breakers(self) -> None:
        lower_priority = {
            "valid_loss": 0.1,
            "report": {
                "accuracy": {"all_fields": 0.8, "priority": 0.7},
                "coverage": 1.0,
            },
        }
        higher_priority = {
            "valid_loss": 0.2,
            "report": {
                "accuracy": {"all_fields": 0.8, "priority": 0.8},
                "coverage": 1.0,
            },
        }
        self.assertIs(
            max([lower_priority, higher_priority], key=fine_tune.validation_rank),
            higher_priority,
        )

    @patch("fine_tune_documents.time.sleep")
    @patch("fine_tune_documents.classify_document")
    @patch("fine_tune_documents.create_openai_client")
    @patch("fine_tune_documents.request_error_types", return_value=(ConnectionError,))
    def test_waits_for_checkpoint_deployment_readiness(
        self,
        _errors: Mock,
        _client: Mock,
        classify: Mock,
        sleep: Mock,
    ) -> None:
        classify.side_effect = [ConnectionError("not ready"), {"priority": "High"}]
        deployment = Deployment("00a", "account", "base", project_name="project")
        document = SimpleNamespace(
            index=1,
            text="document",
            expected={
                "document_type": "Contract",
                "department": "Legal",
                "priority": "High",
            },
        )

        fine_tune.wait_for_deployment(deployment, "checkpoint", document)

        self.assertEqual(classify.call_count, 2)
        sleep.assert_called_once_with(30)


class FineTuningJobTests(unittest.TestCase):
    @patch("fine_tune_documents.prepare")
    @patch("fine_tune_documents.create_openai_client")
    @patch("fine_tune_documents.load_deployment")
    def test_submit_uses_developer_three_epoch_configuration(
        self, load_deployment: Mock, create_client: Mock, prepare_data: Mock
    ) -> None:
        load_deployment.return_value = Deployment(
            "00a",
            "account",
            "gpt-4.1-mini",
            project_name="project",
            resource_group="rg",
            subscription_id="sub",
        )
        prepare_data.return_value = {"training_rows": 78, "validation_rows": 12}
        client = create_client.return_value
        client.files.create.side_effect = [
            SimpleNamespace(id="train-file"),
            SimpleNamespace(id="validation-file"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "training.jsonl").write_text("training", encoding="utf-8")
            (data_dir / "validation.jsonl").write_text("validation", encoding="utf-8")
            state_path = data_dir / "state.json"
            with patch("fine_tune_documents.fine_tuning_request") as request_job:
                request_job.return_value = {"id": "job-123", "status": "pending"}
                state = fine_tune.submit_job("scenario", state_path, data_dir)

        request = request_job.call_args.args[3]
        create_client.assert_called_once_with(
            load_deployment.return_value.fine_tuning_base_url,
            fine_tune.COGNITIVE_SERVICES_SCOPE,
        )
        self.assertEqual(request["model"], fine_tune.BASE_MODEL)
        self.assertEqual(request["trainingType"], "developerTier")
        hyperparameters = request["method"]["supervised"]["hyperparameters"]
        self.assertEqual(hyperparameters["n_epochs"], 3)
        self.assertEqual(hyperparameters["learning_rate_multiplier"], 0.5)
        self.assertEqual(state["job_id"], "job-123")

    def test_existing_job_state_prevents_duplicate_submission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text('{"job_id":"job-existing"}', encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "already contains job"):
                fine_tune.submit_job("scenario", state_path)

    @patch("fine_tune_documents.subprocess.run")
    def test_azure_cli_failures_are_explicit(self, run: Mock) -> None:
        run.return_value = SimpleNamespace(returncode=1, stderr="quota exceeded", stdout="")
        with self.assertRaisesRegex(RuntimeError, "quota exceeded"):
            fine_tune.run_az(["example"])


if __name__ == "__main__":
    unittest.main()
