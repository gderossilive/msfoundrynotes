#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'Usage: %s <00a|00c> <azd-environment-name>\n' "$0" >&2
  exit 2
fi

lane_id="$1"
environment_name="$2"
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
case "$lane_id" in
  00a) scenario_dir="$repo_root/scenarios/00-foundry-core/00a-foundry-core-public" ;;
  00c) scenario_dir="$repo_root/scenarios/00-foundry-core/00c-foundry-core-byo-vnet" ;;
  *) printf 'Lane must be 00a or 00c.\n' >&2; exit 2 ;;
esac
source "$repo_root/scripts/security-checks.sh"

get_value() {
  (
    cd "$scenario_dir"
    AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env get-value "$1" \
      --environment "$environment_name"
  )
}

resource_group=$(get_value AZURE_RESOURCE_GROUP)
apim_name=$(get_value AZURE_APIM_NAME)
allowed_principal_ids=$(get_value AZURE_APIM_ALLOWED_PRINCIPAL_IDS)

# azd prints its "key not found" error on stdout, so an unset optional value must be detected by exit status.
get_optional_value() {
  local value
  if value=$(get_value "$1" 2>/dev/null); then
    printf '%s' "$value"
  fi
}

tokens_per_minute=$(get_optional_value AZURE_APIM_TOKENS_PER_MINUTE)
tokens_per_minute=${tokens_per_minute:-0}
usage_metrics=$(get_optional_value AZURE_APIM_USAGE_METRICS)
usage_metrics=${usage_metrics:-false}

[[ -n "$resource_group" && -n "$apim_name" ]] || {
  printf 'The selected azd environment is missing %s gateway deployment outputs.\n' "$lane_id" >&2
  exit 2
}

if ! validate_apim_tokens_per_minute "$tokens_per_minute"; then
  printf 'AZURE_APIM_TOKENS_PER_MINUTE must be an integer from 0 to 10000000; 0 disables the limit.\n' >&2
  exit 2
fi

if [[ "$usage_metrics" != true && "$usage_metrics" != false ]]; then
  printf 'AZURE_APIM_USAGE_METRICS must be true or false.\n' >&2
  exit 2
fi

if ! validate_apim_principal_ids "$allowed_principal_ids"; then
  printf 'AZURE_APIM_ALLOWED_PRINCIPAL_IDS must be a JSON array of at most 100 Entra object IDs.\n' >&2
  exit 2
fi

outputs=$(az deployment group create \
  --resource-group "$resource_group" \
  --template-file "$scenario_dir/infra/apim-policy.bicep" \
  --parameters apimName="$apim_name" allowedPrincipalIds="$allowed_principal_ids" \
  tokensPerMinute="$tokens_per_minute" enableUsageMetrics="$usage_metrics" \
  --name "apply-${lane_id}-apim-policy" \
  --query properties.outputs --output json)

if [[ "$usage_metrics" == true ]]; then
  for pair in AZURE_USAGE_WORKSPACE_ID:usageWorkspaceId AZURE_USAGE_WORKSPACE_CUSTOMER_ID:usageWorkspaceCustomerId; do
    (
      cd "$scenario_dir"
      AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set "${pair%%:*}" \
        "$(jq -r --arg key "${pair##*:}" '.[$key].value' <<<"$outputs")" \
        --environment "$environment_name"
    )
  done
fi
printf 'Policy applied (token limit: %s tokens/min; usage metrics: %s).\n' "$tokens_per_minute" "$usage_metrics"
