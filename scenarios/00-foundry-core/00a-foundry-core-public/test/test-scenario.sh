#!/usr/bin/env bash
set -Eeuo pipefail
scenario_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
repo_root=$(cd "$scenario_root/../../.." && pwd)
"$repo_root/scripts/test-scenario.sh" "$scenario_root" "${1:---static}"
(
  cd "$scenario_root/../app"
  python3 -m unittest -v \
    test_chat_completions.py \
    test_benchmark_documents.py \
    test_prepare_finetuning_data.py \
    test_fine_tune_documents.py
)

grep -q "c883944f-8b7b-4483-af10-35834be79c4a" "$scenario_root/infra/main.bicep"
if grep -q "53ca6127-db72-4b80-b1b0-d745d6d5456d" "$scenario_root/infra/main.bicep"; then
  echo "Foundry User must not remain assigned when Foundry Owner is required." >&2
  exit 1
fi
