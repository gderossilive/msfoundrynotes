#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s <azd-environment-name>\n' "$0" >&2
  exit 2
fi

environment_name="$1"
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
scenario_dir="$repo_root/scenarios/00-foundry-core/00c-foundry-core-byo-vnet"
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

[[ -n "$resource_group" && -n "$apim_name" ]] || {
  printf 'The selected azd environment is missing 00c deployment outputs.\n' >&2
  exit 2
}

if ! validate_apim_principal_ids "$allowed_principal_ids"; then
  printf 'AZURE_APIM_ALLOWED_PRINCIPAL_IDS must be a JSON array of at most 100 Entra object IDs.\n' >&2
  exit 2
fi

az deployment group create \
  --resource-group "$resource_group" \
  --template-file "$scenario_dir/infra/apim-policy.bicep" \
  --parameters apimName="$apim_name" allowedPrincipalIds="$allowed_principal_ids" \
  --name apply-00c-apim-policy
