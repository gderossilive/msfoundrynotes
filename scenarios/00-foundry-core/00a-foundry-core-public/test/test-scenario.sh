#!/usr/bin/env bash
set -Eeuo pipefail
scenario_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
repo_root=$(cd "$scenario_root/../../.." && pwd)
"$repo_root/scripts/test-scenario.sh" "$scenario_root" "${1:---static}"
(
  cd "$scenario_root/../app"
  python3 -m unittest -v \
    test_chat_completions.py \
    test_benchmark_documents.py
)

grep -q "53ca6127-db72-4b80-b1b0-d745d6d5456d" "$scenario_root/infra/main.bicep"
