#!/usr/bin/env bash

set -Eeuo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_root/scripts/scenario-metadata.sh"
test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT

pass_count=0

pass() {
  printf '[PASS] %s\n' "$1"
  pass_count=$((pass_count + 1))
}

expect_failure() {
  local expected="$1"
  shift
  local output
  if output=$("$@" 2>&1); then
    printf '[FAIL] Expected command to fail: %s\n' "$*" >&2
    exit 1
  fi
  [[ "$output" == *"$expected"* ]] || {
    printf '[FAIL] Expected %q in output: %s\n' "$expected" "$output" >&2
    exit 1
  }
  pass "$expected"
}

make_lane() {
  local relative_path="$1"
  mkdir -p "$test_root/scenarios/$relative_path"
  : >"$test_root/scenarios/$relative_path/azure.yaml"
}

make_lane '02-standard-agent/02a-standard-agent-public'
resolve_scenario_lane "$test_root" '02-standard-agent/02a-standard-agent-public'
[[ "$SCENARIO_LEVEL_ID" == 02 ]]
[[ "$SCENARIO_LANE_ID" == 02a ]]
[[ "$SCENARIO_NETWORK_PROFILE" == a ]]
pass 'public lane resolves'

make_lane '02-standard-agent/02b-standard-agent-managed-vnet'
resolve_scenario_lane "$test_root" '02-standard-agent/02b-standard-agent-managed-vnet'
[[ "$SCENARIO_NETWORK_PROFILE" == b ]]
pass 'managed lane resolves'

make_lane '02-standard-agent/02c-standard-agent-byo-vnet'
resolve_scenario_lane "$test_root" '02-standard-agent/02c-standard-agent-byo-vnet'
[[ "$SCENARIO_NETWORK_PROFILE" == c ]]
pass 'BYO lane resolves'

expect_failure 'does not contain azure.yaml' resolve_scenario_lane "$test_root" '02-standard-agent'
expect_failure 'must be relative' resolve_scenario_lane "$test_root" /tmp/scenario

make_lane '03-standard-agent/02a-standard-agent-public'
expect_failure 'does not match level' resolve_scenario_lane "$test_root" '03-standard-agent/02a-standard-agent-public'

make_lane '04-standard-agent-apim/04b-standard-agent-apim-public'
expect_failure 'invalid profile and network suffix combination' resolve_scenario_lane "$test_root" '04-standard-agent-apim/04b-standard-agent-apim-public'

printf 'Completed %d scenario metadata checks.\n' "$pass_count"