#!/usr/bin/env bash
set -Eeuo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
mode="${1:---static}"
scenario_filter="${2:-}"

case "$mode" in
  --static) ;;
  --live|--e2e)
    [[ -n "$scenario_filter" ]] || {
      printf 'Usage: %s --live <scenario>\nUsage: %s --e2e <private-scenario>\n' "$0" "$0" >&2
      exit 2
    }
    ;;
  --help|-h)
    printf 'Usage: %s [--static]\nUsage: %s --live <scenario>\nUsage: %s --e2e <private-scenario>\n' "$0" "$0" "$0"
    exit 0
    ;;
  *)
    printf 'Unknown mode: %s\n' "$mode" >&2
    exit 2
    ;;
esac

mapfile -t scenarios < <(find "$repo_root/scenarios" -mindepth 3 -maxdepth 3 -type f -name azure.yaml -printf '%h\n' | sort)
[[ "${#scenarios[@]}" -gt 0 ]] || {
  printf '[FAIL] No deployable scenario lanes were found.\n' >&2
  exit 1
}

if [[ -n "$scenario_filter" ]]; then
  scenarios=("$repo_root/scenarios/$scenario_filter")
fi

if [[ "$mode" == --static ]]; then
  bash "$repo_root/scripts/test-bootstrap-scenario-env.sh"
  bash "$repo_root/scripts/test-scenario-metadata.sh"
fi

for scenario_dir in "${scenarios[@]}"; do
  scenario="${scenario_dir#"$repo_root/scenarios/"}"
  [[ -f "$scenario_dir/azure.yaml" ]] || {
    printf '[FAIL] Scenario lane %s does not contain azure.yaml\n' "$scenario" >&2
    exit 1
  }
  test_script="$scenario_dir/test/test-scenario.sh"
  [[ -x "$test_script" ]] || {
    printf '[FAIL] Missing executable test for %s\n' "$scenario" >&2
    exit 1
  }
  printf '\n=== %s %s ===\n' "$scenario" "$mode"
  "$test_script" "$mode"
done

printf '\nAll requested scenario tests passed.\n'
