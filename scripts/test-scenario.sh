#!/usr/bin/env bash

set -Eeuo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  printf 'Usage: %s <scenario-root> [--static|--live|--e2e]\n' "$0" >&2
  exit 2
fi

scenario_root=$(cd "$1" && pwd)
repo_root=$(cd "$scenario_root/../../.." && pwd)
source "$repo_root/scripts/security-checks.sh"
source "$repo_root/scripts/scenario-metadata.sh"
resolve_scenario_lane "$repo_root" "${scenario_root#"$repo_root/scenarios/"}"
scenario=$(basename "$scenario_root")
scenario_id="$SCENARIO_LEVEL_ID"
lane_id="$SCENARIO_LANE_ID"
level_root="$SCENARIO_LEVEL_DIR"
mode="${2:---static}"
environment_name="${TEST_AZD_ENV:-}"
pass_count=0

pass() {
  printf '[PASS] %s\n' "$1"
  pass_count=$((pass_count + 1))
}

fail() {
  printf '[FAIL] %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command is missing: $1"
}

get_env_value() {
  local value
  if ! value=$(cd "$scenario_root" && AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env get-value "$1" \
    --environment "$environment_name" 2>/dev/null); then
    value=''
  fi
  printf '%s' "$value"
}

assert_value() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  [[ "${actual,,}" == "${expected,,}" ]] || fail "$label: expected $expected, got ${actual:-<empty>}"
  pass "$label"
}

check_private_endpoint() {
  local label="$1"
  local resource_id="$2"
  local statuses
  statuses=$(az network private-endpoint-connection list \
    --id "$resource_id" \
    --query '[].properties.privateLinkServiceConnectionState.status' \
    -o tsv 2>/dev/null || true)
  [[ -n "$statuses" ]] || fail "$label: no private endpoint connection found"
  local invalid
  invalid=$(printf '%s\n' "$statuses" | awk 'NF && tolower($0) != "approved" { count++ } END { print count + 0 }')
  [[ "$invalid" == "0" ]] || fail "$label: connection is not Approved ($statuses)"
  pass "$label: Approved"
}

run_static() {
  require_command az
  local required_file
  for required_file in \
    "$scenario_root/azure.yaml" \
    "$scenario_root/README.md" \
    "$scenario_root/infra/main.bicep" \
    "$scenario_root/infra/main.bicepparam" \
    "$level_root/app/README.md"
  do
    [[ -f "$required_file" ]] || fail "Missing required file: $required_file"
  done
  pass "required scenario files"

  az bicep build --file "$scenario_root/infra/main.bicep" --stdout >/dev/null
  pass "Bicep build"

  if [[ "$lane_id" == 00b || "$lane_id" == 00c ]]; then
    check_core_private_static
  fi

  if [[ "$lane_id" == 01c ]]; then
    check_private_security_static
  fi

  grep -q 'path: ./infra' "$scenario_root/azure.yaml" || fail 'azure.yaml does not point to ./infra'
  grep -q 'module: main' "$scenario_root/azure.yaml" || fail 'azure.yaml does not select main'
  pass "azd scenario contract"

  if grep -R -n 'scenarios/' "$scenario_root/infra" >/dev/null 2>&1; then
    fail 'Scenario infrastructure references another scenario'
  fi
  pass "deployment independence"

  if [[ "$scenario_id" == 00 ]]; then
    return
  fi

  [[ -f "$level_root/blog/$(basename "$level_root").md" ]] || fail 'Missing level blog article'
  local expected_sections=(
    '## Hook iniziale'
    '## Il problema reale'
    '## Come Foundry affronta lo scenario'
    '## Valore pratico'
    '## Mini-visual'
    '## Call to action'
  )
  local section_index=0
  while IFS= read -r section; do
    [[ "$section_index" -lt "${#expected_sections[@]}" ]] || fail 'Blog contains too many level-two sections'
    [[ "$section" == "${expected_sections[$section_index]}" ]] \
      || fail "Blog section $((section_index + 1)) is '$section', expected '${expected_sections[$section_index]}'"
    section_index=$((section_index + 1))
  done < <(grep '^## ' "$level_root/blog/$(basename "$level_root").md" || true)
  [[ "$section_index" -eq "${#expected_sections[@]}" ]] || fail 'Blog is missing required sections'
  pass "blog contract"
}

check_core_private_static() {
  require_command jq
  local template
  template=$(az bicep build --file "$scenario_root/infra/main.bicep" --stdout)
  jq -e '
    [.. | objects | select(.type? == "Microsoft.CognitiveServices/accounts")] as $accounts |
    ($accounts | length == 1) and
    ([.. | objects | select(has("parameters")) |
      .parameters.userAssignedIdentityResourceId? | select(. != null) | .defaultValue] == [""]) and
    ([.. | objects | select(.type? == "Microsoft.Resources/deployments") |
      select(.properties.parameters.publicNetworkAccess.value? == "Disabled" and
             .properties.parameters.disableLocalAuth.value? == true)] | length == 1) and
    ([.. | objects | select(.type? == "Microsoft.Network/virtualNetworks")] | length == 1) and
    ([.. | objects | select(.type? == "Microsoft.Network/privateEndpoints") |
      select(.properties.privateLinkServiceConnections[0].properties.groupIds == ["account"])] | length == 1) and
    ([.. | objects | select(.type? == "Microsoft.Network/privateEndpoints/privateDnsZoneGroups") |
      .properties.privateDnsZoneConfigs | length] == [3]) and
    ([.. | objects | select(.type? == "Microsoft.Network/privateDnsZones/virtualNetworkLinks") |
      .properties.registrationEnabled] == [false]) and
    ([.. | objects | select(.foundryZoneNames? == [
      "privatelink.cognitiveservices.azure.com", "privatelink.openai.azure.com",
      "privatelink.services.ai.azure.com"])] | length == 1) and
    ([.. | objects | .type? // empty | select(test("capabilityHosts|Microsoft.App/"))] | length == 0) and
    ([.. | objects | select(has("delegations"))] | length == 0)
  ' <<<"$template" >/dev/null || fail 'Core private resource and security contract'
  pass 'Core private resource and security contract'

  if [[ "$lane_id" == 00b ]]; then
    jq -e '
      ([.. | objects | select(.type? == "Microsoft.Resources/deployments") |
        .properties.parameters.enableManagedNetwork.value? | select(. == true)] | length == 1) and
      ([.. | objects | select(.type? == "Microsoft.CognitiveServices/accounts/managedNetworks") |
        select(.apiVersion == "2026-05-15-preview") |
        .properties.managedNetwork |
        select(.isolationMode == "AllowInternetOutbound" and .managedNetworkKind == "V2" and
               .outboundRules.foundry.type == "PrivateEndpoint" and
               .outboundRules.foundry.destination.subresourceTarget == "account")] | length == 1) and
      ([.. | objects | select(.type? == "Microsoft.Authorization/roleAssignments") |
        select(.scope | contains("Microsoft.CognitiveServices/accounts"))] | length == 1)
    ' <<<"$template" >/dev/null || fail 'Core managed network and account-scoped approver contract'
    pass 'Core managed network and account-scoped approver contract'
    return
  fi

  jq -e '
    ([.. | objects | select(has("parameters")) |
      .parameters.enableManagedNetwork? | select(has("defaultValue")) | .defaultValue] == [false, false]) and
    ([.. | objects | select(.type? == "Microsoft.Resources/deployments") |
      .properties.parameters.enableManagedNetwork.value? | select(. == true)] | length == 0) and
    ([.. | objects | select(.type? == "Microsoft.CognitiveServices/accounts/managedNetworks")] | length == 0)
  ' <<<"$template" >/dev/null || fail '00c must not configure agent network injection or a managed network'
  pass '00c has no agent network injection or managed network'
}

run_live() {
  require_command az
  require_command azd
  [[ -n "$environment_name" ]] || fail 'TEST_AZD_ENV is required for live and e2e checks'

  local resource_group account project model principal
  resource_group=$(get_env_value AZURE_RESOURCE_GROUP)
  account=$(get_env_value AZURE_AI_ACCOUNT_NAME)
  project=$(get_env_value AZURE_AI_PROJECT_NAME)
  model=$(get_env_value AZURE_AI_MODEL_DEPLOYMENT_NAME)
  principal=$(get_env_value AZURE_AI_PROJECT_PRINCIPAL_ID)
  [[ -n "$resource_group" && -n "$account" && -n "$project" && -n "$model" ]] \
    || fail "azd environment '$environment_name' is missing Foundry outputs"

  local group_state
  group_state=$(az group show --name "$resource_group" --query properties.provisioningState -o tsv 2>/dev/null || true)
  [[ -n "$group_state" ]] || fail "resource group '$resource_group' was not found for azd environment '$environment_name'"
  assert_value "resource group" "Succeeded" "$group_state"

  local account_id project_id deployment_id
  account_id=$(get_env_value AZURE_AI_ACCOUNT_ID)
  project_id=$(get_env_value AZURE_AI_PROJECT_ID)
  local account_check project_check
  account_check=$(az rest --method get \
    --url "https://management.azure.com${account_id}?api-version=2025-04-01-preview" \
    --query id -o tsv 2>/dev/null || true)
  project_check=$(az rest --method get \
    --url "https://management.azure.com${project_id}?api-version=2025-04-01-preview" \
    --query id -o tsv 2>/dev/null || true)
  deployment_id=$(az rest --method get \
    --url "https://management.azure.com${account_id}/deployments/${model}?api-version=2025-04-01-preview" \
    --query id -o tsv 2>/dev/null || true)
  [[ -n "$account_id" ]] || fail 'Foundry account output is missing'
  [[ -n "$project_id" ]] || fail 'Foundry project output is missing'
  [[ -n "$account_check" ]] || fail "Foundry account '$account' was not found"
  [[ -n "$project_check" ]] || fail "Foundry project '$project' was not found"
  [[ -n "$deployment_id" ]] || fail "Model deployment '$model' is missing"
  pass "Foundry account, project and model"

  local account_pna account_local_auth
  account_pna=$(az cognitiveservices account show --name "$account" --resource-group "$resource_group" --query properties.publicNetworkAccess -o tsv)
  account_local_auth=$(az cognitiveservices account show --name "$account" --resource-group "$resource_group" --query properties.disableLocalAuth -o tsv)

  case "$lane_id" in
    00a|01a)
      assert_value "Foundry public network access" "Enabled" "$account_pna"
      assert_value "Foundry local auth" "true" "$account_local_auth"
      ;;
    02a)
      assert_value "Foundry public network access" "Enabled" "$account_pna"
      assert_value "Foundry local auth" "true" "$account_local_auth"
      ;;
    03a|04a|05a)
      assert_value "Foundry public network access" "Enabled" "$account_pna"
      assert_value "Foundry local auth" "true" "$account_local_auth"
      ;;
    00b|00c|01c)
      assert_value "Foundry public network access" "Disabled" "$account_pna"
      assert_value "Foundry local auth" "true" "$account_local_auth"
      ;;
    *)
      fail "No generic live profile exists for lane $lane_id"
      ;;
  esac

  local capability_host
  capability_host=$(get_env_value AZURE_AI_CAPABILITY_HOST_ID)
  if [[ -n "$capability_host" ]]; then
    local host_state
    host_state=$(az rest --method get \
      --url "https://management.azure.com${capability_host}?api-version=2025-04-01-preview" \
      --query properties.provisioningState -o tsv)
    assert_value "capability host state" "Succeeded" "$host_state"
  elif [[ "$lane_id" == 01a || "$lane_id" == 02a || "$lane_id" == 03a || "$lane_id" == 04a || "$lane_id" == 05a ]]; then
    fail "Lane $lane_id must expose a capability host"
  else
    pass "no capability host required"
  fi

  if [[ "$scenario_id" != 00 ]]; then
    check_prompt_agent "$account" "$project"
  fi

  case "$lane_id" in
    00b|00c)
      check_private_endpoint 'Foundry private endpoint' "$account_id"
      local endpoint_id endpoint_state dns_count account_identity project_identity
      endpoint_id=$(get_env_value AZURE_AI_PRIVATE_ENDPOINT_ID)
      [[ -n "$endpoint_id" ]] || fail 'Core private endpoint output is missing'
      endpoint_state=$(az rest --method get --url "https://management.azure.com${endpoint_id}?api-version=2024-05-01" \
        --query properties.provisioningState -o tsv)
      assert_value 'Core private endpoint state' 'Succeeded' "$endpoint_state"
      dns_count=$(az rest --method get --url "https://management.azure.com${endpoint_id}/privateDnsZoneGroups?api-version=2024-05-01" \
        --query 'length(value[0].properties.privateDnsZoneConfigs)' -o tsv)
      assert_value 'Core private DNS zone count' '3' "$dns_count"
      account_identity=$(az rest --method get --url "https://management.azure.com${account_id}?api-version=2025-04-01-preview" \
        --query identity.type -o tsv)
      project_identity=$(az rest --method get --url "https://management.azure.com${project_id}?api-version=2025-04-01-preview" \
        --query identity.type -o tsv)
      assert_value 'Core account identity' 'SystemAssigned' "$account_identity"
      assert_value 'Core project identity' 'SystemAssigned' "$project_identity"
      if [[ "$lane_id" == 00b ]]; then
        local managed_network_id isolation_mode managed_injection outbound_target
        managed_network_id=$(get_env_value AZURE_AI_MANAGED_NETWORK_ID)
        [[ -n "$managed_network_id" ]] || fail 'Core managed network output is missing'
        isolation_mode=$(az rest --method get --url "https://management.azure.com${managed_network_id}?api-version=2026-05-15-preview" \
          --query properties.managedNetwork.isolationMode -o tsv)
        assert_value 'Core managed isolation mode' 'AllowInternetOutbound' "$isolation_mode"
        managed_injection=$(az rest --method get --url "https://management.azure.com${account_id}?api-version=2026-05-01" \
          --query 'properties.networkInjections[0].useMicrosoftManagedNetwork' -o tsv)
        assert_value 'Core managed network injection' 'true' "$managed_injection"
        outbound_target=$(az rest --method get --url "https://management.azure.com${managed_network_id}?api-version=2026-05-15-preview" \
          --query properties.managedNetwork.outboundRules.foundry.destination.serviceResourceId -o tsv)
        assert_value 'Core managed private endpoint target' "$account_id" "$outbound_target"
      fi
      ;;
    02a|03a|04a|05a)
      check_standard_public "$resource_group" "$project" "$principal"
      ;;
    01c)
      check_private_basic "$resource_group" "$account_id"
      check_private_security_live
      ;;
  esac
}

check_prompt_agent() {
  local account="$1"
  local project="$2"
  local agent_name agent_version expected_name agent
  agent_name=$(get_env_value AZURE_AI_AGENT_NAME)
  agent_version=$(get_env_value AZURE_AI_AGENT_VERSION)
  expected_name=$(jq -r '.name' "$level_root/app/agent.json")
  assert_value "Foundry prompt agent name" "$expected_name" "$agent_name"
  [[ "$agent_version" =~ ^[0-9]+$ ]] || fail 'Foundry prompt agent version is missing or invalid'
  agent=$(az rest --method get --resource https://ai.azure.com \
    --url "https://${account}.services.ai.azure.com/api/projects/${project}/agents/${agent_name}/versions/${agent_version}?api-version=v1" \
    --query name -o tsv 2>/dev/null || true)
  assert_value "Foundry prompt agent version" "$agent_name" "$agent"
}

check_standard_public() {
  local resource_group="$1"
  local project="$2"
  local principal="$3"
  local storage search cosmos capability_host
  storage=$(get_env_value AZURE_STORAGE_ACCOUNT_NAME)
  search=$(get_env_value AZURE_SEARCH_SERVICE_NAME)
  cosmos=$(get_env_value AZURE_COSMOS_ACCOUNT_NAME)
  capability_host=$(get_env_value AZURE_AI_CAPABILITY_HOST_ID)
  [[ -n "$storage" && -n "$search" && -n "$cosmos" ]] || fail 'Standard Agent outputs are missing'

  assert_value "Storage public network access" "Enabled" "$(az storage account show --name "$storage" --resource-group "$resource_group" --query publicNetworkAccess -o tsv)"
  assert_value "Search public network access" "enabled" "$(az search service show --name "$search" --resource-group "$resource_group" --query publicNetworkAccess -o tsv)"
  assert_value "Cosmos public network access" "Enabled" "$(az cosmosdb show --name "$cosmos" --resource-group "$resource_group" --query publicNetworkAccess -o tsv)"

  local vector storage_connection thread
  vector=$(az rest --method get --url "https://management.azure.com${capability_host}?api-version=2025-04-01-preview" --query 'properties.vectorStoreConnections[0]' -o tsv)
  storage_connection=$(az rest --method get --url "https://management.azure.com${capability_host}?api-version=2025-04-01-preview" --query 'properties.storageConnections[0]' -o tsv)
  thread=$(az rest --method get --url "https://management.azure.com${capability_host}?api-version=2025-04-01-preview" --query 'properties.threadStorageConnections[0]' -o tsv)
  assert_value "public vector store connection" "$search" "$vector"
  assert_value "public storage connection" "$storage" "$storage_connection"
  assert_value "public thread storage connection" "$cosmos" "$thread"

  local scope role count
  for scope in \
    "$(get_env_value AZURE_STORAGE_ACCOUNT_ID)|Storage Blob Data Contributor" \
    "$(get_env_value AZURE_SEARCH_SERVICE_ID)|Search Index Data Contributor" \
    "$(get_env_value AZURE_COSMOS_ACCOUNT_ID)|Cosmos DB Operator"
  do
    role="${scope#*|}"
    scope="${scope%%|*}"
    count=$(az role assignment list --scope "$scope" --assignee "$principal" --query "[?roleDefinitionName=='$role'] | length(@)" -o tsv)
    [[ "$count" -ge 1 ]] || fail "Missing RBAC role '$role'"
    pass "RBAC $role"
  done
}

check_private_basic() {
  local resource_group="$1"
  local account_id="$2"
  local agent_subnet_id private_endpoint_id delegation_count
  agent_subnet_id=$(get_env_value AZURE_AGENT_SUBNET_ID)
  private_endpoint_id=$(get_env_value AZURE_AI_PRIVATE_ENDPOINT_ID)
  delegation_count=$(az network vnet subnet show --ids "$agent_subnet_id" --query "length(delegations[?serviceName=='Microsoft.App/environments'])" -o tsv)
  [[ "$delegation_count" -ge 1 ]] || fail 'Private Basic Agent subnet is not delegated to Microsoft.App/environments'
  pass "private agent subnet delegation"
  check_private_endpoint "Foundry private endpoint" "$account_id"
  [[ -n "$private_endpoint_id" ]] || fail 'Foundry private endpoint output is missing'
  pass "Foundry private endpoint output"
}

e2e_tunnel_log=''
e2e_tunnel_pid=''

cleanup_e2e_tunnel() {
  if [[ -n "${e2e_tunnel_pid:-}" ]] && kill -0 "$e2e_tunnel_pid" 2>/dev/null; then
    kill -TERM -- "-$e2e_tunnel_pid" 2>/dev/null || kill "$e2e_tunnel_pid" 2>/dev/null || true
    wait "$e2e_tunnel_pid" 2>/dev/null || true
  fi
  [[ -z "${e2e_tunnel_log:-}" ]] || rm -f "$e2e_tunnel_log"
  e2e_tunnel_pid=''
  e2e_tunnel_log=''
}

run_e2e() {
  [[ "$lane_id" == 01c ]] || fail "Generic e2e mode is supported for private lane 01c only; later lanes have their own suites"
  require_command az
  require_command ssh
  require_command setsid
  local resource_group bastion_id vm_id account model key_path port
  resource_group=$(get_env_value AZURE_RESOURCE_GROUP)
  bastion_id=$(get_env_value AZURE_BASTION_ID)
  vm_id=$(get_env_value AZURE_JUMPBOX_VM_ID)
  account=$(get_env_value AZURE_AI_ACCOUNT_NAME)
  model=$(get_env_value AZURE_AI_MODEL_DEPLOYMENT_NAME)
  key_path="${JUMPBOX_SSH_KEY_PATH:-$HOME/.ssh/foundrylab-jumpbox-recovery}"
  port="${TEST_TUNNEL_PORT:-50026}"
  [[ -f "$key_path" ]] || fail "SSH private key not found: $key_path"
  [[ -n "$bastion_id" && -n "$vm_id" ]] || fail 'Jumpbox outputs are missing'
  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "Local tunnel port $port is already in use; set TEST_TUNNEL_PORT to a free port"
  fi

  e2e_tunnel_log=$(mktemp)
  trap cleanup_e2e_tunnel EXIT
  setsid az network bastion tunnel --resource-group "$resource_group" --name "${bastion_id##*/}" \
    --target-resource-id "$vm_id" --resource-port 22 --port "$port" >"$e2e_tunnel_log" 2>&1 &
  e2e_tunnel_pid=$!

  local attempt
  for attempt in $(seq 1 30); do
    grep -q 'Tunnel is ready' "$e2e_tunnel_log" && break
    kill -0 "$e2e_tunnel_pid" 2>/dev/null || { cat "$e2e_tunnel_log" >&2; fail 'Bastion tunnel exited'; }
    IFS= read -r -t 1 _ < <(tail -n 0 -f "$e2e_tunnel_log") || true
  done
  grep -q 'Tunnel is ready' "$e2e_tunnel_log" || { cat "$e2e_tunnel_log" >&2; fail 'Bastion tunnel did not become ready'; }

  ssh -i "$key_path" -p "$port" -o StrictHostKeyChecking=yes -o BatchMode=yes -o IdentitiesOnly=yes \
    -o "HostKeyAlias=$vm_id" -o "UserKnownHostsFile=${JUMPBOX_SSH_KNOWN_HOSTS:-$HOME/.ssh/known_hosts}" \
    -o ConnectTimeout=10 azureuser@127.0.0.1 "ACCOUNT=$account MODEL=$model bash -s" <<'REMOTE'
set -Eeuo pipefail
ip=$(getent ahostsv4 "$ACCOUNT.openai.azure.com" | awk 'NR==1 {print $1}')
case "$ip" in 10.*|192.168.*|172.16.*|172.17.*|172.18.*|172.19.*|172.2[0-9].*|172.3[0-1].*) ;; *) exit 1 ;; esac
TOKEN=$(curl -fsS -H Metadata:true 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2019-08-01&resource=https%3A%2F%2Fcognitiveservices.azure.com%2F' | sed -n 's/.*"access_token":"\([^"]*\).*/\1/p')
test -n "$TOKEN"
response=$(curl -fsS "https://$ACCOUNT.openai.azure.com/openai/deployments/$MODEL/chat/completions?api-version=2025-04-01-preview" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"Reply with exactly OK."}],"max_completion_tokens":128}')
grep -q '"object":"chat.completion"' <<<"$response"
grep -q '"content":"OK"' <<<"$response"
REMOTE
  pass 'private DNS, IMDS token and model invocation'
  cleanup_e2e_tunnel
  trap - EXIT
}

case "$mode" in
  --static) run_static ;;
  --live) run_static; run_live ;;
  --e2e) run_static; run_live; run_e2e ;;
  --help|-h) printf 'Usage: %s <scenario-root> [--static|--live|--e2e]\n' "$0" ;;
  *) printf 'Unknown mode: %s\n' "$mode" >&2; exit 2 ;;
esac

printf 'Completed %d checks for %s in %s mode.\n' "$pass_count" "$scenario" "$mode"
