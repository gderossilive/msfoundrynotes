#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 3 || ( "$2" != create && "$2" != cleanup ) ]]; then
  printf 'Usage: %s <00a|00c> <create|cleanup> <azd-environment-name>\n' "$0" >&2
  exit 2
fi

lane_id="$1"
action="$2"
environment_name="$3"
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
case "$lane_id" in
  00a) scenario_dir="$repo_root/scenarios/00-foundry-core/00a-foundry-core-public" ;;
  00c) scenario_dir="$repo_root/scenarios/00-foundry-core/00c-foundry-core-byo-vnet" ;;
  *) printf 'Lane must be 00a or 00c.\n' >&2; exit 2 ;;
esac
state_dir="$repo_root/.azure/${lane_id}-second-caller/$environment_name"
state_file="$state_dir/state.json"
source "$repo_root/scripts/security-checks.sh"

get_allowlist() {
  (
    cd "$scenario_dir"
    AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env get-value AZURE_APIM_ALLOWED_PRINCIPAL_IDS \
      --environment "$environment_name"
  )
}

set_allowlist() {
  (
    cd "$scenario_dir"
    AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set AZURE_APIM_ALLOWED_PRINCIPAL_IDS "$1" \
      --environment "$environment_name"
  )
}

if [[ "$action" == create ]]; then
  [[ ! -e "$state_file" ]] || {
    printf 'A second caller already exists for %s. Run cleanup first.\n' "$environment_name" >&2
    exit 2
  }
  allowlist=$(get_allowlist)
  validate_apim_principal_ids "$allowlist" || {
    printf 'AZURE_APIM_ALLOWED_PRINCIPAL_IDS must be a JSON array of at most 100 Entra object IDs.\n' >&2
    exit 2
  }

  umask 077
  mkdir -p "$state_dir/az"
  tenant_id=$(az account show --query tenantId --output tsv)

  # The service principal receives no Azure role: it only needs an identity for the gateway token.
  app_id=$(az ad app create --display-name "foundrylab-${lane_id}-caller-b-$environment_name" \
    --query appId --output tsv)
  sp_object_id=$(az ad sp create --id "$app_id" --query id --output tsv)
  jq -n --arg appId "$app_id" --arg spObjectId "$sp_object_id" \
    '{appId: $appId, servicePrincipalObjectId: $spObjectId}' >"$state_file"

  # A certificate keeps the credential out of process arguments; it expires after one day.
  generated_pem=$(az ad app credential reset --id "$app_id" --create-cert \
    --end-date "$(date -u -d '+1 day' +%Y-%m-%d)" --query fileWithCertAndPrivateKey --output tsv)
  mv "$generated_pem" "$state_dir/caller-b.pem"
  chmod 600 "$state_dir/caller-b.pem"

  for attempt in 1 2 3 4 5 6; do
    if AZURE_CONFIG_DIR="$state_dir/az" az login --service-principal --username "$app_id" \
      --certificate "$state_dir/caller-b.pem" --tenant "$tenant_id" --allow-no-subscriptions \
      --output none 2>/dev/null; then
      signed_in=true
      break
    fi
    sleep 10
  done
  [[ "${signed_in:-false}" == true ]] || {
    printf 'The second caller could not sign in. Run cleanup and retry.\n' >&2
    exit 1
  }

  set_allowlist "$(jq -c --arg id "$sp_object_id" '. + [$id] | unique' <<<"$allowlist")"
  printf 'Second caller created. Azure CLI profile: %s/az\n' "$state_dir"
  printf 'Apply the policy next: scripts/apply-gateway-policy.sh %s %s\n' "$lane_id" "$environment_name"
  exit 0
fi

[[ -f "$state_file" ]] || {
  printf 'No second caller recorded for %s.\n' "$environment_name" >&2
  exit 2
}
app_id=$(jq -r .appId "$state_file")
sp_object_id=$(jq -r .servicePrincipalObjectId "$state_file")
set_allowlist "$(jq -c --arg id "$sp_object_id" 'map(select(. != $id))' <<<"$(get_allowlist)")"
az ad app delete --id "$app_id"
rm -rf "$state_dir"
printf 'Second caller removed. Apply the policy again: scripts/apply-gateway-policy.sh %s %s\n' "$lane_id" "$environment_name"
