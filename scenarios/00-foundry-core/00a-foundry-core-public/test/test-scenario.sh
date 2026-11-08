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
    test_monitor_model.py \
    test_prepare_finetuning_data.py \
    test_fine_tune_documents.py \
    test_token_limit_demo.py \
    test_usage_report.py
)

grep -q "c883944f-8b7b-4483-af10-35834be79c4a" "$scenario_root/infra/main.bicep"
if grep -q "53ca6127-db72-4b80-b1b0-d745d6d5456d" "$scenario_root/infra/main.bicep"; then
  echo "Foundry User must not remain assigned when Foundry Owner is required." >&2
  exit 1
fi

template=$(az bicep build --file "$scenario_root/infra/main.bicep" --stdout)
jq -e '
  (.parameters.enableMonitoring.defaultValue == false) and
  ([.resources[] | select(.type == "Microsoft.Resources/deployments" and
    .condition == "[parameters('\''enableMonitoring'\'')]") |
    .properties.template.resources[] |
    select(.type == "Microsoft.Insights/components" and
      .properties.DisableLocalAuth == true)] | length == 1) and
  ([.resources[] | select(.type == "Microsoft.Resources/deployments" and
    .condition == "[parameters('\''enableMonitoring'\'')]") |
    .properties.template.resources[] |
    select(.type == "Microsoft.OperationalInsights/workspaces" and
      .properties.retentionInDays == 30)] | length == 1) and
  ([.resources[] | select(.type == "Microsoft.Resources/deployments" and
    .condition == "[parameters('\''enableMonitoring'\'')]") |
    .properties.template.resources[] |
    select(.type == "Microsoft.Insights/diagnosticSettings") |
    .properties.logs[].category] | sort == ["Audit", "RequestResponse"]) and
  (.outputs.AZURE_MONITORING_APPLICATION_INSIGHTS_ID.value | contains("if("))
' <<<"$template" >/dev/null || {
  echo '00a monitoring must remain opt-in with Entra ingestion and selective diagnostics.' >&2
  exit 1
}

jq -e '
  (.parameters.enableGateway.defaultValue == false) and
  (.parameters.gatewaySkuName.defaultValue == "BasicV2") and
  (.parameters.gatewaySkuName.allowedValues | sort == ["BasicV2", "StandardV2"]) and
  ([.resources[] | select(.type == "Microsoft.Resources/deployments" and
    .condition == "[parameters('\''enableGateway'\'')]" and
    (.dependsOn | index("foundryProject") != null))] | length == 1) and
  (.outputs.AZURE_APIM_CHAT_COMPLETIONS_ENDPOINT.value | contains("if(")) and
  (.outputs.AZURE_APIM_NAME.value | contains("if(")) and
  ([.. | objects | select(.type? == "Microsoft.ApiManagement/service")] | length == 1)
' <<<"$template" >/dev/null || {
  echo '00a gateway must remain opt-in, serialized after the Foundry project and limited to one API Management service.' >&2
  exit 1
}

gateway_template=$(az bicep build --file "$repo_root/modules/apim/foundry-public-gateway/main.bicep" --stdout)
jq -e '
  (.parameters.skuName.allowedValues | sort == ["BasicV2", "StandardV2"]) and
  ([.. | objects | select(.type? == "Microsoft.ApiManagement/service") |
    select(.identity.type == "SystemAssigned" and
           (.properties | has("virtualNetworkType") | not) and
           (.properties | has("virtualNetworkConfiguration") | not))] | length == 1) and
  ([.. | objects | select(.type? == "Microsoft.ApiManagement/service/apis") |
    select(.properties.path == "openai/v1" and .properties.subscriptionRequired == false)] | length == 1) and
  ([.. | objects | select(.type? == "Microsoft.ApiManagement/service/apis/policies")] | length == 0) and
  ([.. | objects | select(.type? == "Microsoft.Authorization/roleAssignments") |
    select(.properties.principalType == "ServicePrincipal" and
           (.properties.roleDefinitionId | contains("5e0bd9bd-7b93-4f28-af87-19fc36ad61bd")))] | length == 1)
' <<<"$gateway_template" >/dev/null || {
  echo '00a gateway module must be a public v2 gateway with managed identity, no policy at deployment and one backend role.' >&2
  exit 1
}

# The account stays public and the deployer keeps its direct role: the gateway is an extra door.
jq -e '
  ([.. | objects | select(.type? == "Microsoft.Resources/deployments") |
    select(.properties.parameters.disableLocalAuth.value? == true)] | length == 1) and
  ([.resources[] | select(.type == "Microsoft.Resources/deployments") |
    .properties.parameters.publicNetworkAccess] | all(. == null))
' <<<"$template" >/dev/null || {
  echo '00a must keep a public account with local authentication disabled, even with the gateway profile.' >&2
  exit 1
}

# 00a and 00c apply the same policy through thin wrappers: they must not drift apart.
policy_a=$(grep -v "Name of the existing API Management" "$scenario_root/infra/apim-policy.bicep")
policy_c=$(grep -v "Name of the existing API Management" "$repo_root/scenarios/00-foundry-core/00c-foundry-core-byo-vnet/infra/apim-policy.bicep")
[[ "$policy_a" == "$policy_c" ]] || {
  echo '00a and 00c apim-policy.bicep wrappers must stay identical.' >&2
  exit 1
}
az bicep build --file "$scenario_root/infra/apim-policy.bicep" --stdout >/dev/null
echo '[PASS] 00a optional gateway contract'
