import codecs
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import prepare_finetuning_data as prepare
from chat_completions import ConfigurationError


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


class FineTuningDatasetTests(unittest.TestCase):
    def test_source_and_heldout_are_exactly_aligned(self) -> None:
        source = prepare.load_rows(prepare.SOURCE_PATH)
        heldout = prepare.load_rows(prepare.HELDOUT_PATH)

        training, validation, manifest = prepare.split_rows(source, heldout)

        self.assertEqual(source[:10], heldout)
        self.assertEqual(len(training), 78)
        self.assertEqual(len(validation), 12)
        self.assertEqual(Counter(row["document_type"] for row in validation), {
            class_name: 2 for class_name in prepare.EXPECTED_CLASSES
        })
        self.assertEqual(manifest["heldout_rows"], 10)
        split_texts = [
            {row["document_text"] for row in rows}
            for rows in (training, validation, heldout)
        ]
        self.assertFalse(split_texts[0] & split_texts[1])
        self.assertFalse(split_texts[0] & split_texts[2])
        self.assertFalse(split_texts[1] & split_texts[2])

    def test_prepared_files_are_bom_jsonl_and_reproduce_the_benchmark_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            manifest = prepare.prepare(output_dir)
            training_path = output_dir / "training.jsonl"
            validation_path = output_dir / "validation.jsonl"
            self.assertTrue(training_path.read_bytes().startswith(codecs.BOM_UTF8))
            self.assertTrue(validation_path.read_bytes().startswith(codecs.BOM_UTF8))
            training = read_jsonl(training_path)
            validation = read_jsonl(validation_path)

        self.assertEqual(len(training), 78)
        self.assertEqual(len(validation), 12)
        self.assertEqual(manifest["training_rows"], 78)
        first = training[0]["messages"]
        self.assertEqual([message["role"] for message in first], ["system", "user", "assistant"])
        self.assertEqual(first[0]["content"], prepare.SYSTEM_PROMPT)
        self.assertEqual(set(json.loads(first[2]["content"])), set(prepare.FIELDS))

    def test_different_existing_output_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "training.jsonl").write_text("different", encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "--force"):
                prepare.prepare(output_dir)

            manifest = prepare.prepare(output_dir, force=True)

        self.assertEqual(manifest["validation_distribution"], {
            class_name: 2 for class_name in sorted(prepare.EXPECTED_CLASSES)
        })


if __name__ == "__main__":
    unittest.main()
