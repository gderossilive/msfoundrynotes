#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  printf 'Usage: %s <level/lane> [--new-instance]\n' "$0" >&2
  exit 2
fi

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_root/scripts/security-checks.sh"
source "$repo_root/scripts/scenario-metadata.sh"
resolve_scenario_lane "$repo_root" "$1"
scenario_dir="$SCENARIO_LANE_DIR"
env_file="$repo_root/.env"
scenario_id="$SCENARIO_LEVEL_ID"
lane_id="$SCENARIO_LANE_ID"
network_profile="$SCENARIO_NETWORK_PROFILE"
new_instance=false

if [[ ${2:-} == '--new-instance' ]]; then
  new_instance=true
elif [[ $# -eq 2 ]]; then
  printf 'Unknown option "%s".\n' "$2" >&2
  exit 2
fi

if [[ ! -f "$env_file" ]]; then
  printf 'Missing %s. Create it from .env.example.\n' "$env_file" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

for variable in AZURE_TENANT_ID AZURE_SUBSCRIPTION_ID AZURE_LOCATION AZURE_ENV_NAME; do
  if [[ -z "${!variable:-}" ]]; then
    printf 'Required value %s is missing in .env.\n' "$variable" >&2
    exit 2
  fi
done

guid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
if [[ ! "$AZURE_TENANT_ID" =~ $guid_pattern ]] || [[ ! "$AZURE_SUBSCRIPTION_ID" =~ $guid_pattern ]]; then
  printf 'AZURE_TENANT_ID and AZURE_SUBSCRIPTION_ID must be GUIDs.\n' >&2
  exit 2
fi

if [[ ! "$AZURE_LOCATION" =~ ^[a-z0-9]+$ ]] || [[ ! "$AZURE_ENV_NAME" =~ ^[a-z0-9-]{3,20}$ ]]; then
  printf 'AZURE_LOCATION or AZURE_ENV_NAME has an invalid format.\n' >&2
  exit 2
fi

if [[ ! "${AZURE_ENABLE_JUMPBOX:-false}" =~ ^(true|false)$ ]]; then
  printf 'AZURE_ENABLE_JUMPBOX must be true or false.\n' >&2
  exit 2
fi

if [[ "${AZURE_ENABLE_JUMPBOX:-false}" == true && -z "${AZURE_JUMPBOX_SSH_PUBLIC_KEY:-}" ]]; then
  printf 'AZURE_JUMPBOX_SSH_PUBLIC_KEY is required when AZURE_ENABLE_JUMPBOX is true.\n' >&2
  exit 2
fi

if [[ -n "${AZURE_APIM_PUBLISHER_EMAIL:-}" && ! "$AZURE_APIM_PUBLISHER_EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
  printf 'AZURE_APIM_PUBLISHER_EMAIL must be a valid email address.\n' >&2
  exit 2
fi

if [[ ! "$scenario_id" =~ ^[0-9]{2}$ ]]; then
  printf 'Scenario "%s" must start with a two-digit identifier.\n' "$1" >&2
  exit 2
fi

if [[ "$lane_id" == 04c || "$lane_id" == 05c ]]; then
  command -v jq >/dev/null 2>&1 || { printf 'jq is required to validate APIM callers.\n' >&2; exit 2; }
  if ! validate_apim_principal_ids "${AZURE_APIM_ALLOWED_PRINCIPAL_IDS:-[]}"; then
    printf 'AZURE_APIM_ALLOWED_PRINCIPAL_IDS must be a JSON array of at most 100 Entra object IDs.\n' >&2
    exit 2
  fi
fi

managed_compute_settings=()
if [[ "$scenario_id" == 06 ]]; then
  for variable in AZURE_MANAGED_COMPUTE_MODEL_ID AZURE_MANAGED_COMPUTE_DEPLOYMENT_TEMPLATE_ID AZURE_MANAGED_COMPUTE_ACCELERATOR_TYPE; do
    if [[ -z "${!variable:-}" ]]; then
      printf 'Required value %s is missing in .env for level 06.\n' "$variable" >&2
      exit 2
    fi
  done
  model_pattern='^azureml://registries/azure-huggingface/models/[a-zA-Z0-9._-]+/versions/[a-zA-Z0-9._-]+$'
  template_pattern='^azureml://registries/azure-huggingface/deploymenttemplates/[a-zA-Z0-9._-]+/(versions|labels)/[a-zA-Z0-9._-]+$'
  if [[ ! "$AZURE_MANAGED_COMPUTE_MODEL_ID" =~ $model_pattern || ! "$AZURE_MANAGED_COMPUTE_DEPLOYMENT_TEMPLATE_ID" =~ $template_pattern ]]; then
    printf 'Managed Compute requires a versioned model URI and a template version or label URI from azure-huggingface.\n' >&2
    exit 2
  fi
  if [[ ! "$AZURE_MANAGED_COMPUTE_ACCELERATOR_TYPE" =~ ^(A100_80GB|H100_80GB|MI_300_192GB)$ ]]; then
    printf 'AZURE_MANAGED_COMPUTE_ACCELERATOR_TYPE must be A100_80GB, H100_80GB or MI_300_192GB.\n' >&2
    exit 2
  fi
  deployment_name="${AZURE_MANAGED_COMPUTE_DEPLOYMENT_NAME:-open-model}"
  instance_count="${AZURE_MANAGED_COMPUTE_INSTANCE_COUNT:-1}"
  principal_type="${AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_TYPE:-ServicePrincipal}"
  if [[ ! "$deployment_name" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$ ]]; then
    printf 'AZURE_MANAGED_COMPUTE_DEPLOYMENT_NAME has an invalid format.\n' >&2
    exit 2
  fi
  if [[ ! "$instance_count" =~ ^[1-9][0-9]{0,9}$ ]] || (( instance_count > 2147483647 )); then
    printf 'AZURE_MANAGED_COMPUTE_INSTANCE_COUNT must be a positive 32-bit integer (model instances, not TPM).\n' >&2
    exit 2
  fi
  if [[ -n "${AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_ID:-}" && ! "$AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_ID" =~ $guid_pattern ]]; then
    printf 'AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_ID must be an Entra object ID (GUID), not a credential.\n' >&2
    exit 2
  fi
  if [[ ! "$principal_type" =~ ^(User|Group|ServicePrincipal)$ ]]; then
    printf 'AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_TYPE must be User, Group or ServicePrincipal.\n' >&2
    exit 2
  fi
  managed_compute_settings=(
    "AZURE_MANAGED_COMPUTE_DEPLOYMENT_NAME=$deployment_name"
    "AZURE_MANAGED_COMPUTE_MODEL_ID=$AZURE_MANAGED_COMPUTE_MODEL_ID"
    "AZURE_MANAGED_COMPUTE_DEPLOYMENT_TEMPLATE_ID=$AZURE_MANAGED_COMPUTE_DEPLOYMENT_TEMPLATE_ID"
    "AZURE_MANAGED_COMPUTE_ACCELERATOR_TYPE=$AZURE_MANAGED_COMPUTE_ACCELERATOR_TYPE"
    "AZURE_MANAGED_COMPUTE_INSTANCE_COUNT=$instance_count"
    "AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_ID=${AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_ID:-}"
    "AZURE_MANAGED_COMPUTE_INFERENCE_PRINCIPAL_TYPE=$principal_type"
  )
fi

cd "$scenario_dir"

azd_environment_name="$AZURE_ENV_NAME"

if [[ "$new_instance" == true ]]; then
  instance_token=$(LC_ALL=C od -An -N4 -tx4 /dev/urandom | tr -d ' \n')
  azd_environment_name="${AZURE_ENV_NAME}-${instance_token}"
  if [[ ${#azd_environment_name} -gt 20 ]]; then
    printf 'AZURE_ENV_NAME is too long to create a new instance environment.\n' >&2
    exit 2
  fi
  azd env new "$azd_environment_name"
elif ! azd env select "$azd_environment_name" >/dev/null 2>&1; then
  azd env new "$azd_environment_name"
fi

assert_environment_binding() {
  local variable_name="$1"
  local expected_value="$2"
  local bound_value

  if ! bound_value=$(azd env get-value "$variable_name" --environment "$azd_environment_name" 2>/dev/null); then
    bound_value=''
  fi
  if [[ -n "$bound_value" && "$bound_value" != "$expected_value" ]]; then
    printf 'azd environment "%s" is already bound to %s="%s".\n' "$azd_environment_name" "$variable_name" "$bound_value" >&2
    exit 2
  fi
}

assert_environment_binding FOUNDRY_SCENARIO_LEVEL_ID "$scenario_id"
assert_environment_binding FOUNDRY_SCENARIO_LANE_ID "$lane_id"
assert_environment_binding FOUNDRY_NETWORK_PROFILE "$network_profile"
assert_environment_binding FOUNDRY_AZD_ENVIRONMENT "$azd_environment_name"
assert_environment_binding AZURE_TENANT_ID "$AZURE_TENANT_ID"
assert_environment_binding AZURE_SUBSCRIPTION_ID "$AZURE_SUBSCRIPTION_ID"
assert_environment_binding AZURE_LOCATION "$AZURE_LOCATION"

if ! resource_group_token=$(azd env get-value AZURE_RESOURCE_GROUP_TOKEN --environment "$azd_environment_name" 2>/dev/null); then
  resource_group_token=''
fi
if [[ -n "$resource_group_token" && ! "$resource_group_token" =~ ^[0-9a-f]{8}$ ]]; then
  printf 'azd environment "%s" has an invalid AZURE_RESOURCE_GROUP_TOKEN.\n' "$azd_environment_name" >&2
  exit 2
fi
if [[ -z "$resource_group_token" ]]; then
  resource_group_token=$(LC_ALL=C od -An -N4 -tx4 /dev/urandom | tr -d ' \n')
fi
resource_group="rg-foundrylab-${lane_id}-${azd_environment_name}-${resource_group_token}"
assert_environment_binding AZURE_RESOURCE_GROUP_TOKEN "$resource_group_token"
assert_environment_binding AZURE_RESOURCE_GROUP "$resource_group"

if ! az group exists --name "$resource_group" --subscription "$AZURE_SUBSCRIPTION_ID" | grep -qx true; then
  az group create \
    --name "$resource_group" \
    --location "$AZURE_LOCATION" \
    --subscription "$AZURE_SUBSCRIPTION_ID" \
    --tags SecurityControl=Ignore \
    --output none
else
  az group update \
    --name "$resource_group" \
    --subscription "$AZURE_SUBSCRIPTION_ID" \
    --set tags.SecurityControl=Ignore \
    --output none
fi

azd env set \
  --environment "$azd_environment_name" \
  "FOUNDRY_SCENARIO_LEVEL_ID=$scenario_id" \
  "FOUNDRY_SCENARIO_LANE_ID=$lane_id" \
  "FOUNDRY_NETWORK_PROFILE=$network_profile" \
  "FOUNDRY_AZD_ENVIRONMENT=$azd_environment_name" \
  "AZURE_TENANT_ID=$AZURE_TENANT_ID" \
  "AZURE_SUBSCRIPTION_ID=$AZURE_SUBSCRIPTION_ID" \
  "AZURE_LOCATION=$AZURE_LOCATION" \
  "AZURE_RESOURCE_GROUP_TOKEN=$resource_group_token" \
  "AZURE_RESOURCE_GROUP=$resource_group" \
  "AZURE_DEFAULT_MODEL=${AZURE_DEFAULT_MODEL:-gpt-5-mini}" \
  "AZURE_DEFAULT_MODEL_VERSION=${AZURE_DEFAULT_MODEL_VERSION:-2025-08-07}" \
  "AZURE_DEFAULT_MODEL_SKU=${AZURE_DEFAULT_MODEL_SKU:-GlobalStandard}" \
  "AZURE_DEFAULT_MODEL_CAPACITY=${AZURE_DEFAULT_MODEL_CAPACITY:-30}" \
  "AZURE_ENABLE_JUMPBOX=${AZURE_ENABLE_JUMPBOX:-false}" \
  "AZURE_JUMPBOX_SSH_PUBLIC_KEY=${AZURE_JUMPBOX_SSH_PUBLIC_KEY:-}" \
  "AZURE_APIM_PUBLISHER_EMAIL=${AZURE_APIM_PUBLISHER_EMAIL:-platform-team@example.com}" \
  "AZURE_APIM_PUBLISHER_NAME=${AZURE_APIM_PUBLISHER_NAME:-FoundryLab platform team}" \
  "AZURE_APIM_SKU=${AZURE_APIM_SKU:-StandardV2}" \
  "AZURE_APIM_CAPACITY=${AZURE_APIM_CAPACITY:-1}" \
  "AZURE_APIM_DISABLE_PUBLIC_ACCESS=${AZURE_APIM_DISABLE_PUBLIC_ACCESS:-true}" \
  "AZURE_APIM_ALLOWED_PRINCIPAL_IDS=${AZURE_APIM_ALLOWED_PRINCIPAL_IDS:-[]}" \
  "AZURE_APIM_CALLS_PER_MINUTE=${AZURE_APIM_CALLS_PER_MINUTE:-60}" \
  "AZURE_APIM_TOKENS_PER_MINUTE=${AZURE_APIM_TOKENS_PER_MINUTE:-5000}" \
  "AZURE_ENABLE_TOOL_PROBE=${AZURE_ENABLE_TOOL_PROBE:-true}" \
  "${managed_compute_settings[@]}"

printf 'Prepared azd environment "%s" for lane "%s" with resource group "%s".\n' "$azd_environment_name" "$1" "$resource_group"