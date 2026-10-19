#!/usr/bin/env python3

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

from benchmark_documents import FIELDS, SYSTEM_PROMPT, ConfigurationError

SOURCE_PATH = Path(__file__).resolve().parent.parent / "data" / "business_documents_100.json"
HELDOUT_PATH = Path(__file__).resolve().parent / "data" / "business_documents_10.json"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "fine-tuning"
SEED = "foundry-notes-00a-sft-v1"
EXPECTED_CLASSES = {
    "Complaint",
    "Contract",
    "GDPRRequest",
    "Invoice",
    "PurchaseOrder",
    "Resume",
}


def load_rows(path: Path) -> list[dict[str, str]]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot read dataset {path}: {exc}") from exc
    if not isinstance(rows, list) or not rows:
        raise ConfigurationError(f"Dataset {path} must be a non-empty JSON array.")
    expected_keys = {"document_text", *FIELDS}
    for index, row in enumerate(rows, start=1):
        if (
            not isinstance(row, dict)
            or set(row) != expected_keys
            or not all(isinstance(row[key], str) and row[key].strip() for key in expected_keys)
        ):
            raise ConfigurationError(f"Invalid dataset row {index} in {path}.")
    return rows


def split_rows(
    source: list[dict[str, str]], heldout: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    if len(source) != 100 or len(heldout) != 10:
        raise ConfigurationError("Expected exactly 100 source rows and 10 held-out rows.")
    if source[: len(heldout)] != heldout:
        raise ConfigurationError("The held-out benchmark is not the first 10 source rows.")
    texts = [row["document_text"] for row in source]
    if len(set(texts)) != len(texts):
        raise ConfigurationError("The source dataset contains duplicate document text.")

    remaining = source[len(heldout) :]
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in remaining:
        grouped[row["document_type"]].append(row)
    if set(grouped) != EXPECTED_CLASSES or any(len(rows) != 15 for rows in grouped.values()):
        raise ConfigurationError("Expected 15 non-test rows for each of the six document classes.")

    validation_ids: set[int] = set()
    for rows in grouped.values():
        ranked = sorted(
            rows,
            key=lambda row: hashlib.sha256(
                f"{SEED}\0{row['document_text']}".encode("utf-8")
            ).digest(),
        )
        validation_ids.update(id(row) for row in ranked[:2])

    training = [row for row in remaining if id(row) not in validation_ids]
    validation = [row for row in remaining if id(row) in validation_ids]
    if len(training) != 78 or len(validation) != 12:
        raise ConfigurationError("The deterministic split did not produce 78/12 rows.")

    train_texts = {row["document_text"] for row in training}
    validation_texts = {row["document_text"] for row in validation}
    heldout_texts = {row["document_text"] for row in heldout}
    if train_texts & validation_texts or train_texts & heldout_texts or validation_texts & heldout_texts:
        raise ConfigurationError("Training, validation, and held-out datasets overlap.")

    manifest = {
        "seed": SEED,
        "source_rows": len(source),
        "training_rows": len(training),
        "validation_rows": len(validation),
        "heldout_rows": len(heldout),
        "training_distribution": dict(sorted(Counter(row["document_type"] for row in training).items())),
        "validation_distribution": dict(
            sorted(Counter(row["document_type"] for row in validation).items())
        ),
        "heldout_distribution": dict(
            sorted(Counter(row["document_type"] for row in heldout).items())
        ),
    }
    return training, validation, manifest


def to_sft_jsonl(rows: list[dict[str, str]]) -> str:
    lines = []
    for row in rows:
        answer = {field: row[field] for field in FIELDS}
        example = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": row["document_text"]},
                {
                    "role": "assistant",
                    "content": json.dumps(answer, separators=(",", ":")),
                },
            ]
        }
        lines.append(json.dumps(example, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + "\n"


def write_if_consistent(path: Path, content: str, force: bool) -> None:
    encoded = content.encode("utf-8-sig")
    if path.exists() and path.read_bytes() != encoded and not force:
        raise ConfigurationError(f"{path} exists with different content; pass --force to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def prepare(output_dir: Path = DEFAULT_OUTPUT_DIR, force: bool = False) -> dict[str, Any]:
    source = load_rows(SOURCE_PATH)
    heldout = load_rows(HELDOUT_PATH)
    training, validation, manifest = split_rows(source, heldout)
    training_content = to_sft_jsonl(training)
    validation_content = to_sft_jsonl(validation)
    write_if_consistent(output_dir / "training.jsonl", training_content, force)
    write_if_consistent(output_dir / "validation.jsonl", validation_content, force)

    source_bytes = SOURCE_PATH.read_bytes()
    manifest = {
        **manifest,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "training_sha256": hashlib.sha256(training_content.encode("utf-8-sig")).hexdigest(),
        "validation_sha256": hashlib.sha256(validation_content.encode("utf-8-sig")).hexdigest(),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_content = json.dumps(manifest, indent=2) + "\n"
    if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != manifest_content and not force:
        raise ConfigurationError(
            f"{manifest_path} exists with different content; pass --force to replace it."
        )
    manifest_path.write_text(manifest_content, encoding="utf-8")
    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare deterministic SFT data for scenario 00a.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = prepare(args.output_dir, args.force)
    except ConfigurationError as exc:
        print(f"Dataset preparation error: {exc}")
        return 2
    print(
        f"Prepared {manifest['training_rows']} training and "
        f"{manifest['validation_rows']} validation examples in {args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
