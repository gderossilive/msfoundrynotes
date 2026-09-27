#!/usr/bin/env bash

validate_apim_principal_ids() {
  jq -es '
    length == 1 and (.[0] | type == "array" and length <= 100 and all(.[]; type == "string" and
      test("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")))
  ' <<<"$1" >/dev/null
}

check_private_security_static() {
  require_command jq
  local ssh_script="$scenario_root/test/test-scenario.sh"
  [[ "$SCENARIO_LANE_ID" != 01c ]] || ssh_script="$repo_root/scripts/test-scenario.sh"
  grep -q 'StrictHostKeyChecking=yes' "$ssh_script" || fail "SSH must require a trusted host key"
  grep -q 'HostKeyAlias=\$vm_id' "$ssh_script" || fail "SSH trust must be bound to the target VM"
  if grep -q 'StrictHostKeyChecking=no\|UserKnownHostsFile=/dev/null' "$ssh_script"; then
    fail "SSH host verification must not be disabled"
  fi
  pass "SSH trust and bootstrap security contract"
  local template
  template=$(az bicep build --file "$repo_root/modules/observability/private-tracing/main.bicep" --stdout)
  jq -e '
    [.resources[] | select(.type == "Microsoft.Insights/components" or .type == "Microsoft.OperationalInsights/workspaces")] as $resources |
    ($resources | length == 2) and
    all($resources[]; .properties.publicNetworkAccessForIngestion == "Disabled" and .properties.publicNetworkAccessForQuery == "Disabled") and
    ([.resources[] | select((.type | ascii_downcase) == "microsoft.insights/privatelinkscopes")] |
      length == 1 and all(.[]; .properties.accessModeSettings.ingestionAccessMode == "PrivateOnly" and .properties.accessModeSettings.queryAccessMode == "PrivateOnly"))
  ' <<<"$template" >/dev/null || fail "Telemetry must restrict ingestion and queries to Private Link"
  pass "private-only telemetry contract"

  if [[ "$SCENARIO_LANE_ID" == 01c ]]; then
    return
  fi
  template=$(az bicep build --file "$repo_root/modules/standard-agent/private-dependencies/main.bicep" --stdout)
  jq -e '
    [.resources[] | select(.type == "Microsoft.Search/searchServices")] |
    length == 1 and all(.[]; .properties.disableLocalAuth == true and
      .properties.publicNetworkAccess == "disabled" and (.properties | has("authOptions") | not))
  ' <<<"$template" >/dev/null || fail "Private Search must use Entra-only authentication"
  pass "private Search authentication contract"

  if [[ "$SCENARIO_LANE_ID" == 04c || "$SCENARIO_LANE_ID" == 05c ]]; then
    check_gateway_security_static
  fi
}

check_private_security_live() {
  local insights_id workspace_id endpoint_id scope_id resource_id api_version
  insights_id=$(get_env_value APPLICATIONINSIGHTS_RESOURCE_ID)
  endpoint_id=$(get_env_value AZURE_MONITOR_PRIVATE_ENDPOINT_ID)
  [[ -n "$insights_id" && -n "$endpoint_id" ]] || fail "Private telemetry outputs are missing"
  workspace_id=$(az rest --method get --url "https://management.azure.com$insights_id?api-version=2020-02-02" \
    --query properties.WorkspaceResourceId -o tsv)
  scope_id=$(az rest --method get --url "https://management.azure.com$endpoint_id?api-version=2024-05-01" \
    --query 'properties.privateLinkServiceConnections[0].properties.privateLinkServiceId' -o tsv)
  [[ -n "$workspace_id" && -n "$scope_id" ]] || fail "Private telemetry resource links are missing"
  for resource_id in "$insights_id" "$workspace_id"; do
    api_version='2020-02-02'
    [[ "$resource_id" != "$workspace_id" ]] || api_version='2023-09-01'
    assert_value "$resource_id public ingestion" "Disabled" \
      "$(az rest --method get --url "https://management.azure.com$resource_id?api-version=$api_version" --query properties.publicNetworkAccessForIngestion -o tsv)"
    assert_value "$resource_id public queries" "Disabled" \
      "$(az rest --method get --url "https://management.azure.com$resource_id?api-version=$api_version" --query properties.publicNetworkAccessForQuery -o tsv)"
  done
  local access_mode
  for access_mode in ingestionAccessMode queryAccessMode; do
    assert_value "AMPLS $access_mode" "PrivateOnly" \
      "$(az rest --method get --url "https://management.azure.com$scope_id?api-version=2021-07-01-preview" --query "properties.accessModeSettings.$access_mode" -o tsv)"
  done
  if [[ "$SCENARIO_LANE_ID" != 01c ]]; then
    resource_id=$(get_env_value AZURE_SEARCH_SERVICE_ID)
    [[ -n "$resource_id" ]] || fail "Search resource output is missing"
    assert_value "Search local authentication disabled" "true" \
      "$(az rest --method get --url "https://management.azure.com$resource_id?api-version=2024-06-01-preview" --query properties.disableLocalAuth -o tsv)"
  fi
  if [[ "$SCENARIO_LANE_ID" == 04c || "$SCENARIO_LANE_ID" == 05c ]]; then
    check_gateway_security_live
  fi
}

check_gateway_security_static() {
  local candidate
  for candidate in '[]' '["11111111-1111-1111-1111-111111111111"]'; do
    validate_apim_principal_ids "$candidate" || fail "Valid gateway allowlist was rejected"
  done
  for candidate in 'null' '{}' '"*"' '["*"]' '[123]' '[""]' '["------------------------------------"]' 'invalid-json' 'null []' '[] []'; do
    if validate_apim_principal_ids "$candidate" 2>/dev/null; then
      fail "Invalid gateway allowlist was accepted"
    fi
  done
  candidate=$(jq -cn '[range(101) | "11111111-1111-1111-1111-111111111111"]')
  if validate_apim_principal_ids "$candidate"; then
    fail "Oversized gateway allowlist was accepted"
  fi
  pass "gateway allowlist input validation"
  local template
  template=$(az bicep build --file "$repo_root/modules/apim/private-gateway/main.bicep" --stdout)
  jq -e '
    .parameters.allowedPrincipalIds.defaultValue == [] and
    all(.variables.modelsPolicy, .variables.agentsPolicy;
      contains("output-token-variable-name=\"caller-token\"") and
      (index("</validate-azure-ad-token>") < index("CALLER_AUTHORIZATION_PLACEHOLDER")) and
      (index("CALLER_AUTHORIZATION_PLACEHOLDER") < index("<rate-limit-by-key")) and
      (contains("context.Request.Headers") | not) and
      (contains("context.Request.IpAddress") | not) and contains("caller-key")) and
    (.variables.callerAuthorizationTemplate |
      contains("Claims.GetValueOrDefault(\"oid\", \"\")") and
      contains("Claims.GetValueOrDefault(\"tid\", \"\")") and
      contains("string.IsNullOrEmpty") and contains("!JArray.Parse") and
      contains(".Contains((string)context.Variables[\"caller-object-id\"])") and
      contains("<set-status code=\"403\"")) and
    (.variables.callerAuthorizationPolicy | contains("allowedPrincipalIds")) and
    all(.variables.resolvedModelsPolicy, .variables.resolvedAgentsPolicy; contains("callerAuthorizationPolicy")) and
    ([.resources[] | select(.type == "Microsoft.Authorization/roleAssignments" and (.name | contains("Azure AI User")))] |
      length == 1 and all(.[]; .scope | contains("Microsoft.CognitiveServices/accounts/projects")))
  ' <<<"$template" >/dev/null || fail "Gateway must authorize callers before identity-based budgets and use project-scoped RBAC"
  template=$(az bicep build --file "$scenario_root/infra/main.bicep" --stdout)
  jq -e '
    [.resources[] | select(.type == "Microsoft.Resources/deployments")] as $modules |
    any($modules[]; .properties.parameters.grantDirectModelAccess.value == false) and
    any($modules[]; .properties.parameters.allowedPrincipalIds.value == "[parameters('\''apimAllowedPrincipalIds'\'')]")
  ' <<<"$template" >/dev/null || fail "Gateway caller configuration or jumpbox restriction is missing"
  pass "gateway caller authorization and least privilege"
}

check_gateway_security_live() {
  local apim_id account_id project_id principal_id api policy assignments vm_id vm_principal
  apim_id=$(get_env_value AZURE_APIM_ID)
  account_id=$(get_env_value AZURE_AI_ACCOUNT_ID)
  project_id=$(get_env_value AZURE_AI_PROJECT_ID)
  principal_id=$(get_env_value AZURE_APIM_PRINCIPAL_ID)
  [[ -n "$apim_id" && -n "$account_id" && -n "$project_id" && -n "$principal_id" ]] || fail "Gateway outputs are missing"
  for api in foundry-models foundry-agents; do
    policy=$(az rest --method get \
      --url "https://management.azure.com$apim_id/apis/$api/policies/policy?api-version=2024-05-01&format=rawxml" \
      --query properties.value -o tsv)
    grep -q 'output-token-variable-name="caller-token"' <<<"$policy" || fail "$api must use a validated caller token"
    grep -q '!JArray.Parse' <<<"$policy" || fail "$api must enforce a caller allowlist"
    grep -q 'code="403"' <<<"$policy" || fail "$api must reject unauthorized callers"
    grep -q 'caller-key' <<<"$policy" || fail "$api must use identity-based counters"
    if grep -q 'context.Request.Headers\|context.Request.IpAddress\|PLACEHOLDER' <<<"$policy"; then
      fail "$api contains an untrusted counter source or unresolved policy configuration"
    fi
    pass "$api caller authorization"
  done
  assignments=$(az role assignment list --scope "$project_id" --assignee "$principal_id" --include-inherited --all -o json)
  jq -e --arg scope "${project_id,,}" '
    [.[] | select(.roleDefinitionId | endswith("53ca6127-db72-4b80-b1b0-d745d6d5456d"))] |
    length > 0 and all(.[]; (.scope | ascii_downcase) == $scope)
  ' <<<"$assignments" >/dev/null || fail "Gateway Azure AI User must exist only at project scope; review stale or inherited grants"
  pass "gateway project-scoped Azure AI User"
  vm_id=$(get_env_value AZURE_JUMPBOX_VM_ID)
  if [[ -n "$vm_id" ]]; then
    vm_principal=$(az vm show --ids "$vm_id" --query identity.principalId -o tsv)
    [[ -n "$vm_principal" ]] || fail "Jumpbox managed identity is missing"
    assignments=$(az role assignment list --scope "$account_id" --assignee "$vm_principal" --include-inherited --all -o json)
    jq -e 'length == 0' <<<"$assignments" >/dev/null || fail "Jumpbox still has direct or inherited Foundry grants; review and remove obsolete grants explicitly"
    pass "jumpbox has no account-level or inherited Foundry grants"
  fi
}