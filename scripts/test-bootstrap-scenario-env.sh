#!/usr/bin/env bash

set -Eeuo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
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

make_test_repo() {
  mkdir -p "$test_root/scripts" "$test_root/bin" "$test_root/scenarios/01-basic-agent/01a-basic-agent-public"
  cp "$repo_root/scripts/bootstrap-scenario-env.sh" "$repo_root/scripts/scenario-metadata.sh" "$repo_root/scripts/security-checks.sh" "$test_root/scripts/"
  : >"$test_root/scenarios/01-basic-agent/01a-basic-agent-public/azure.yaml"
  cat >"$test_root/.env" <<'EOF'
AZURE_TENANT_ID=11111111-1111-1111-1111-111111111111
AZURE_SUBSCRIPTION_ID=22222222-2222-2222-2222-222222222222
AZURE_LOCATION=italynorth
AZURE_ENV_NAME=test
AZURE_ENABLE_JUMPBOX=false
EOF
  cat >"$test_root/bin/azd" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "$*" >>"$MOCK_AZD_LOG"
case "$1 ${2:-}" in
  'env select'|'env new'|'env set')
    exit 0
    ;;
  'env get-value')
    variable_name="$3"
    if [[ "$variable_name" == AZURE_RESOURCE_GROUP_TOKEN ]]; then
      printf 'a1b2c3d4\n'
    elif [[ "$variable_name" == "${MOCK_AZD_CONFLICT_VARIABLE:-}" ]]; then
      printf '%s\n' "$MOCK_AZD_CONFLICT_VALUE"
    fi
    ;;
esac
EOF
  chmod +x "$test_root/bin/azd"
  cat >"$test_root/bin/az" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "$*" >>"$MOCK_AZ_LOG"
case "$1 ${2:-}" in
  'group exists')
    printf '%s\n' "${MOCK_AZ_GROUP_EXISTS:-false}"
    ;;
esac
EOF
  chmod +x "$test_root/bin/az"
}

run_bootstrap() {
  PATH="$test_root/bin:$PATH" \
    MOCK_AZD_LOG="$test_root/azd.log" \
    MOCK_AZ_LOG="$test_root/az.log" \
    MOCK_AZD_CONFLICT_VARIABLE="${1:-}" \
    MOCK_AZD_CONFLICT_VALUE="${2:-}" \
    bash "$test_root/scripts/bootstrap-scenario-env.sh" "${test_lane:-01-basic-agent/01a-basic-agent-public}"
}

run_bootstrap_existing_group() {
  PATH="$test_root/bin:$PATH" \
    MOCK_AZD_LOG="$test_root/azd.log" \
    MOCK_AZ_LOG="$test_root/az.log" \
    MOCK_AZ_GROUP_EXISTS=true \
    bash "$test_root/scripts/bootstrap-scenario-env.sh" '01-basic-agent/01a-basic-agent-public'
}

make_test_repo

output=$(run_bootstrap)
[[ "$output" == *'Prepared azd environment "test" for lane "01-basic-agent/01a-basic-agent-public" with resource group "rg-foundrylab-01a-test-a1b2c3d4".'* ]]
grep -qx 'group create --name rg-foundrylab-01a-test-a1b2c3d4 --location italynorth --subscription 22222222-2222-2222-2222-222222222222 --tags SecurityControl=Ignore --output none' "$test_root/az.log"
pass 'accepts an unbound environment and persists a deterministic resource group'

: >"$test_root/az.log"
run_bootstrap_existing_group >/dev/null
grep -qx 'group update --name rg-foundrylab-01a-test-a1b2c3d4 --subscription 22222222-2222-2222-2222-222222222222 --set tags.SecurityControl=Ignore --output none' "$test_root/az.log"
pass 'applies the policy exemption tag to an existing resource group'

: >"$test_root/azd.log"
expect_failure 'FOUNDRY_SCENARIO_LANE_ID="02a"' run_bootstrap FOUNDRY_SCENARIO_LANE_ID 02a
! grep -qx 'env set.*' "$test_root/azd.log"
pass 'rejects a lane binding mismatch before environment mutation'

: >"$test_root/azd.log"
expect_failure 'AZURE_RESOURCE_GROUP="rg-other"' run_bootstrap AZURE_RESOURCE_GROUP rg-other
! grep -qx 'env set.*' "$test_root/azd.log"
pass 'rejects a resource group binding mismatch before environment mutation'

! grep -q 'AZURE_MANAGED_COMPUTE_' "$test_root/azd.log"
pass 'does not persist Managed Compute inputs for existing GPT lanes'

for core_lane in 00a-foundry-core-public; do
  test_lane="00-foundry-core/$core_lane"
  mkdir -p "$test_root/scenarios/$test_lane"
  : >"$test_root/scenarios/$test_lane/azure.yaml"
  : >"$test_root/azd.log"
  output=$(run_bootstrap)
  core_id="${core_lane%%-*}"
  [[ "$output" == *"rg-foundrylab-${core_id}-test-a1b2c3d4"* ]]
  grep -q "FOUNDRY_SCENARIO_LANE_ID=$core_id" "$test_root/azd.log"
  grep -q "FOUNDRY_NETWORK_PROFILE=${core_id:2:1}" "$test_root/azd.log"
  ! grep -q 'AZURE_MANAGED_COMPUTE_' "$test_root/azd.log"
  pass "$core_id bootstrap uses its own network profile and resource group"
done

test_lane='06-foundry-managed-compute/06a-foundry-managed-compute-public'
mkdir -p "$test_root/scenarios/$test_lane"
: >"$test_root/scenarios/$test_lane/azure.yaml"
unset AZURE_MANAGED_COMPUTE_MODEL_ID AZURE_MANAGED_COMPUTE_DEPLOYMENT_TEMPLATE_ID AZURE_MANAGED_COMPUTE_ACCELERATOR_TYPE
: >"$test_root/azd.log"
: >"$test_root/az.log"
expect_failure 'AZURE_MANAGED_COMPUTE_MODEL_ID is missing' run_bootstrap
[[ ! -s "$test_root/azd.log" && ! -s "$test_root/az.log" ]]
pass 'rejects missing inputs before any Azure or azd call'

export AZURE_MANAGED_COMPUTE_MODEL_ID='azureml://registries/azure-huggingface/models/qwen--qwen3-32b/versions/1'
export AZURE_MANAGED_COMPUTE_DEPLOYMENT_TEMPLATE_ID='azureml://registries/azure-huggingface/deploymenttemplates/qwen--qwen3-32b--40k-nvidia-a100/labels/latest'
export AZURE_MANAGED_COMPUTE_ACCELERATOR_TYPE=A100_80GB
export AZURE_MANAGED_COMPUTE_DEPLOYMENT_NAME=qwen3-32b
export AZURE_MANAGED_COMPUTE_INSTANCE_COUNT=1
export AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_ID=''
export AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_TYPE=ServicePrincipal
for lane in a b c; do
  case "$lane" in
    a) profile=public ;;
    b) profile=managed-vnet ;;
    c) profile=byo-vnet ;;
  esac
  test_lane="06-foundry-managed-compute/06${lane}-foundry-managed-compute-${profile}"
  mkdir -p "$test_root/scenarios/$test_lane"
  : >"$test_root/scenarios/$test_lane/azure.yaml"
  : >"$test_root/azd.log"
  run_bootstrap >/dev/null
  for variable in AZURE_MANAGED_COMPUTE_DEPLOYMENT_NAME AZURE_MANAGED_COMPUTE_MODEL_ID AZURE_MANAGED_COMPUTE_DEPLOYMENT_TEMPLATE_ID AZURE_MANAGED_COMPUTE_ACCELERATOR_TYPE AZURE_MANAGED_COMPUTE_INSTANCE_COUNT AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_ID AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_TYPE; do
    grep -Fq "$variable=${!variable}" "$test_root/azd.log"
  done
  pass "persists all Managed Compute inputs for 06${lane}"
done

for invalid_setting in \
  'AZURE_MANAGED_COMPUTE_MODEL_ID=https://example.com/model' \
  'AZURE_MANAGED_COMPUTE_DEPLOYMENT_TEMPLATE_ID=invalid-template' \
  'AZURE_MANAGED_COMPUTE_ACCELERATOR_TYPE=unknown' \
  'AZURE_MANAGED_COMPUTE_DEPLOYMENT_NAME=invalid/name' \
  'AZURE_MANAGED_COMPUTE_INSTANCE_COUNT=0' \
  'AZURE_MANAGED_COMPUTE_INSTANCE_COUNT=-1' \
  'AZURE_MANAGED_COMPUTE_INSTANCE_COUNT=1.5' \
  'AZURE_MANAGED_COMPUTE_INSTANCE_COUNT=99999999999999999999999' \
  'AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_ID=invalid-id' \
  'AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_TYPE=invalid-type'; do
  variable="${invalid_setting%%=*}"
  previous_value="${!variable}"
  export "$invalid_setting"
  : >"$test_root/azd.log"
  : >"$test_root/az.log"
  expect_failure '' run_bootstrap
  [[ ! -s "$test_root/azd.log" && ! -s "$test_root/az.log" ]]
  pass "rejects $invalid_setting before any Azure or azd call"
  export "$variable=$previous_value"
done

printf 'Completed %d bootstrap environment checks.\n' "$pass_count"