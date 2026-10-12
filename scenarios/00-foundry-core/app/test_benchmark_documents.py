import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import benchmark_documents as benchmark
from chat_completions import ConfigurationError, Deployment


def completion(content: str | None, finish_reason: str = "stop", refusal: str | None = None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content, refusal=refusal),
            )
        ]
    )


def evaluation_client(valid: int, scores: dict[str, int] | None = None) -> Mock:
    client = Mock()
    scores = scores or dict.fromkeys((*benchmark.FIELDS, "all_fields"), valid)
    client.evals.create.return_value = SimpleNamespace(id="eval_123")
    client.evals.runs.create.return_value = SimpleNamespace(id="run_456", status="queued")
    client.evals.runs.retrieve.return_value = SimpleNamespace(
        id="run_456",
        status="completed",
        report_url="https://foundry.example/evaluation",
        result_counts=SimpleNamespace(total=valid, errored=0),
        per_testing_criteria_results=[
            SimpleNamespace(testing_criteria=field, passed=passed, failed=valid - passed)
            for field, passed in scores.items()
        ],
    )
    return client


class DatasetTests(unittest.TestCase):
    def test_fixture_contains_ten_documents_and_six_types(self) -> None:
        documents = benchmark.load_documents()

        self.assertEqual(len(documents), 10)
        self.assertEqual([doc.index for doc in documents], list(range(1, 11)))
        counts = {kind: sum(doc.expected["document_type"] == kind for doc in documents)
                  for kind in {doc.expected["document_type"] for doc in documents}}
        self.assertEqual(sorted(counts.values()), [1, 1, 2, 2, 2, 2])

    def test_invalid_dataset_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps([{"document_text": "text", "priority": "High"}]))
            with self.assertRaisesRegex(ConfigurationError, "index 1"):
                benchmark.load_documents(path)
            path.write_text("{")
            with self.assertRaisesRegex(ConfigurationError, "Cannot read"):
                benchmark.load_documents(path)


class ClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.documents = benchmark.load_documents()
        self.schema = benchmark.response_format(self.documents)
        self.client = Mock()

    def test_schema_and_classification_request(self) -> None:
        document = self.documents[0]
        self.client.chat.completions.create.return_value = completion(json.dumps(document.expected))

        prediction = benchmark.classify_document(self.client, "gpt-5-mini", document, self.schema)

        self.assertEqual(prediction, document.expected)
        request = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "gpt-5-mini")
        self.assertEqual(request["messages"][1], {"role": "user", "content": document.text})
        self.assertTrue(request["response_format"]["json_schema"]["strict"])
        self.assertEqual(request["response_format"]["json_schema"]["schema"]["required"], list(benchmark.FIELDS))
        self.assertFalse(request["response_format"]["json_schema"]["schema"]["additionalProperties"])
        self.assertIn("Critical", self.schema["json_schema"]["schema"]["properties"]["priority"]["enum"])

    def test_bad_model_responses_are_recorded_without_aborting(self) -> None:
        examples = [
            completion("not json"),
            completion('{"document_type":"Other","department":"Legal","priority":"High"}'),
            completion('{"document_type":"Invoice"}'),
            completion(None),
            completion(None, refusal="Cannot help"),
            completion("{}", finish_reason="length"),
            SimpleNamespace(choices=[]),
        ]
        for response in examples:
            with self.subTest(response=response):
                self.client.chat.completions.create.side_effect = [
                    response, completion(json.dumps(self.documents[1].expected))
                ]
                results, rows = benchmark.collect_predictions(self.client, "model", self.documents[:2])
                self.assertEqual(results[0]["status"], "error")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["expected_document_type"], self.documents[1].expected["document_type"])

    def test_flattens_labels_for_foundry_graders(self) -> None:
        first, second = self.documents[:2]
        wrong = dict(second.expected, priority=first.expected["priority"])
        self.client.chat.completions.create.side_effect = [
            completion(json.dumps(first.expected)), completion(json.dumps(wrong))
        ]
        results, rows = benchmark.collect_predictions(self.client, "model", [first, second])
        self.assertEqual([result["status"] for result in results], ["valid", "valid"])
        self.assertEqual(rows[1]["expected_priority"], second.expected["priority"])
        self.assertEqual(rows[1]["predicted_priority"], wrong["priority"])
        self.assertNotEqual(rows[1]["expected_all_fields"], rows[1]["predicted_all_fields"])
        self.assertEqual(set(rows[0]), {
            f"{side}_{field}" for side in ("expected", "predicted")
            for field in (*benchmark.FIELDS, "all_fields")
        })
        self.assertNotIn(first.text, json.dumps(rows))

        self.client.chat.completions.create.side_effect = None
        self.client.chat.completions.create.return_value = completion("invalid")
        results, rows = benchmark.collect_predictions(self.client, "model", [first])
        self.assertEqual(results[0]["status"], "error")
        self.assertEqual(rows, [])

    def test_request_errors_are_not_counted_as_invalid_responses(self) -> None:
        self.client.chat.completions.create.side_effect = ConnectionError("offline")
        with self.assertRaises(ConnectionError):
            benchmark.collect_predictions(self.client, "model", self.documents)


class FoundryEvaluationTests(unittest.TestCase):
    @patch("benchmark_documents.time.sleep")
    def test_uses_native_string_check_graders_and_cloud_scores(self, sleep: Mock) -> None:
        client = evaluation_client(2, {
            "document_type": 2, "department": 2, "priority": 1, "all_fields": 1
        })
        rows = [
            {f"{side}_{field}": "value" for side in ("expected", "predicted")
             for field in (*benchmark.FIELDS, "all_fields")}
            for _ in range(2)
        ]
        result = benchmark.run_foundry_evaluation(client, rows)
        criteria = client.evals.create.call_args.kwargs["testing_criteria"]
        self.assertEqual(len(criteria), 4)
        self.assertEqual(criteria[2], {
            "type": "string_check",
            "name": "priority",
            "input": "{{item.predicted_priority}}",
            "reference": "{{item.expected_priority}}",
            "operation": "eq",
        })
        source = client.evals.runs.create.call_args.kwargs["data_source"]["source"]
        self.assertEqual(source, {"type": "file_content", "content": [{"item": row} for row in rows]})
        client.evals.runs.retrieve.assert_called_once_with(eval_id="eval_123", run_id="run_456")
        self.assertEqual(result["accuracy"], {
            "document_type": 1.0, "department": 1.0, "priority": 0.5, "all_fields": 0.5
        })
        self.assertEqual(result["report_url"], "https://foundry.example/evaluation")
        sleep.assert_called_once_with(5)

    def test_rejects_empty_or_incomplete_foundry_scores(self) -> None:
        client = evaluation_client(1)
        with self.assertRaisesRegex(ConfigurationError, "No valid"):
            benchmark.run_foundry_evaluation(client, [])
        client.evals.runs.retrieve.return_value.per_testing_criteria_results = []
        with patch("benchmark_documents.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "incomplete grader results"):
                benchmark.run_foundry_evaluation(client, [{"expected_priority": "High"}])

    def test_surfaces_failed_run_with_ids(self) -> None:
        client = evaluation_client(1)
        client.evals.runs.retrieve.return_value.status = "failed"
        client.evals.runs.retrieve.return_value.error = "permission denied"
        with patch("benchmark_documents.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "eval_123/run_456 failed: permission denied"):
                benchmark.run_foundry_evaluation(client, [{"expected_priority": "High"}])

    def test_times_out_with_recoverable_run_ids(self) -> None:
        client = evaluation_client(1)
        with patch("benchmark_documents.time.monotonic", side_effect=[0, 600]):
            with self.assertRaisesRegex(RuntimeError, "eval_123/run_456 did not finish"):
                benchmark.run_foundry_evaluation(client, [{"expected_priority": "High"}])


class MainTests(unittest.TestCase):
    @patch("benchmark_documents.request_error_types", return_value=(ConnectionError, RuntimeError))
    @patch("benchmark_documents.create_openai_client")
    @patch("benchmark_documents.load_deployment")
    def test_report_is_written_without_document_text(
        self, load_deployment: Mock, create_client: Mock, _errors: Mock
    ) -> None:
        load_deployment.return_value = Deployment("00a", "account123", "model", project_name="core")
        model_client = Mock()
        model_client.chat.completions.create.side_effect = [
            completion(json.dumps(doc.expected)) for doc in benchmark.load_documents()
        ]
        create_client.side_effect = [model_client, evaluation_client(10)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch("builtins.print"), patch("benchmark_documents.time.sleep"):
                status = benchmark.main(["--environment", "dev", "--output", str(path)])
            report_text = path.read_text()
            report = json.loads(report_text)
        self.assertEqual(status, 0)
        load_deployment.assert_called_once_with("dev", "00a")
        self.assertEqual([call.args[0] for call in create_client.call_args_list], [
            load_deployment.return_value.direct_base_url,
            load_deployment.return_value.project_base_url,
        ])
        self.assertEqual(report["sample_size"], 10)
        self.assertEqual(report["accuracy"]["all_fields"], 1.0)
        self.assertEqual(report["evaluation_id"], "eval_123")
        self.assertNotIn(benchmark.load_documents()[0].text, report_text)

    @patch("benchmark_documents.request_error_types", return_value=(ConnectionError,))
    @patch("benchmark_documents.create_openai_client")
    @patch("benchmark_documents.load_deployment")
    def test_can_override_the_environment_model_deployment(
        self, load_deployment: Mock, create_client: Mock, _errors: Mock
    ) -> None:
        load_deployment.return_value = Deployment("00a", "account123", "base", project_name="core")
        model_client = Mock()
        model_client.chat.completions.create.side_effect = [
            completion(json.dumps(doc.expected)) for doc in benchmark.load_documents()
        ]
        create_client.side_effect = [model_client, evaluation_client(10)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch("builtins.print"), patch("benchmark_documents.time.sleep"):
                status = benchmark.main([
                    "--environment",
                    "dev",
                    "--deployment-name",
                    "fine-tuned",
                    "--output",
                    str(path),
                ])
            report = json.loads(path.read_text())

        self.assertEqual(status, 0)
        self.assertEqual(report["model"], "fine-tuned")
        requested_models = [
            call.kwargs["model"] for call in model_client.chat.completions.create.call_args_list
        ]
        self.assertEqual(set(requested_models), {"fine-tuned"})

    @patch("benchmark_documents.request_error_types", return_value=(ConnectionError, RuntimeError))
    @patch("benchmark_documents.create_openai_client")
    @patch("benchmark_documents.load_deployment")
    def test_api_failure_does_not_write_report(
        self, load_deployment: Mock, create_client: Mock, _errors: Mock
    ) -> None:
        load_deployment.return_value = Deployment("00a", "account123", "model", project_name="core")
        create_client.return_value.chat.completions.create.side_effect = ConnectionError("offline")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch("sys.stderr"):
                status = benchmark.main(["--environment", "dev", "--output", str(path)])
            self.assertEqual(status, 1)
            self.assertFalse(path.exists())

    @patch("benchmark_documents.request_error_types", return_value=(ConnectionError, RuntimeError))
    @patch("benchmark_documents.create_openai_client")
    @patch("benchmark_documents.load_deployment")
    def test_no_valid_classifications_record_errors_without_cloud_run(
        self, load_deployment: Mock, create_client: Mock, _errors: Mock
    ) -> None:
        load_deployment.return_value = Deployment("00a", "account123", "model", project_name="core")
        create_client.return_value.chat.completions.create.return_value = completion("not json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch("sys.stderr"):
                status = benchmark.main(["--environment", "dev", "--output", str(path)])
            self.assertEqual(status, 1)
            report = json.loads(path.read_text())
            self.assertEqual(report["errors"], 10)
            self.assertEqual(report["evaluation_status"], "not_run")
            self.assertIsNone(report["accuracy"]["priority"])
            self.assertEqual(create_client.call_count, 1)

    @patch("benchmark_documents.request_error_types", return_value=(ConnectionError,))
    @patch("benchmark_documents.create_openai_client")
    @patch("benchmark_documents.load_deployment")
    def test_failed_cloud_run_does_not_write_success_report(
        self, load_deployment: Mock, create_client: Mock, _errors: Mock
    ) -> None:
        load_deployment.return_value = Deployment("00a", "account123", "model", project_name="core")
        model_client = Mock()
        model_client.chat.completions.create.return_value = completion(
            json.dumps(benchmark.load_documents()[0].expected)
        )
        cloud_client = evaluation_client(10)
        cloud_client.evals.runs.retrieve.return_value.status = "failed"
        cloud_client.evals.runs.retrieve.return_value.error = "no permission"
        create_client.side_effect = [model_client, cloud_client]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch("sys.stderr"), patch("benchmark_documents.time.sleep"):
                status = benchmark.main(["--environment", "dev", "--output", str(path)])
            self.assertEqual(status, 1)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
