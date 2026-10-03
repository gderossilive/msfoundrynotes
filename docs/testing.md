# Testing and inference

Run the local checks before provisioning. Live checks and inference require a
separately authorized Azure deployment and can incur costs. The current package
contains only the 00a public lane.

## Local static checks

From the repository root:

```bash
bash scripts/test-all-scenarios.sh --static
```

The runner checks bootstrap and scenario metadata with mocked Azure commands,
then compiles 00a and validates its scenario contract. It does
not call Azure provisioning APIs. Core has no scenario-local blog requirement.

Compile the parameter files as well, using either their defaults or explicitly
exported non-secret model settings:

```bash
for parameters in scenarios/00-foundry-core/*/infra/main.bicepparam; do
  az bicep build-params --file "$parameters" --stdout >/dev/null || exit 1
done
```

## Live resource checks

From the lane you actually deployed, set the exact lane-local environment name.
The value below is an example, not a discovered deployment:

```bash
cd scenarios/00-foundry-core/00a-foundry-core-public
export TEST_AZD_ENV=dev
azd env get-value AZURE_RESOURCE_GROUP --environment "$TEST_AZD_ENV"
azd env get-value AZURE_SUBSCRIPTION_ID --environment "$TEST_AZD_ENV"
```

Confirm both values refer to your intended deployment. If outputs are missing
after successful provisioning, refresh that environment with
`azd env refresh --environment "$TEST_AZD_ENV"`, then check them again.

```bash
subscription=$(azd env get-value AZURE_SUBSCRIPTION_ID --environment "$TEST_AZD_ENV")
az account set --subscription "$subscription"
bash test/test-scenario.sh --live
```

Live checks inspect the deployed resources and model. These control-plane checks
do not send an inference request or prove that the caller can reach and use the
model endpoint.

For the repository's Python inference client, setup instructions, and mocked
unit tests, see the
[Chat Completions sample](../scenarios/00-foundry-core/app/README.md).

## Caller authorization

For the account-level Azure OpenAI endpoint used below, the calling identity
needs an inference role, for example **Cognitive Services OpenAI User** scoped
to the Foundry resource. See the official
[Azure OpenAI role guidance](https://learn.microsoft.com/azure/foundry/openai/how-to/role-based-access-control).
An administrator with role-assignment permission must grant access if it is not
already present. Assign it to the actual caller, not automatically to the project
identity. Allow time for role propagation.

The templates do not grant the deploying user inference access. `az rest` uses
the current Azure CLI identity and obtains its token internally; do not extract,
print, paste or persist bearer tokens. Do not enable shell tracing (`set -x`) or
CLI debug logging for authentication and inference commands.

## Manual keyless inference

The example targets a chat-completions-compatible model such as the sample
`gpt-5-mini` deployment. Other model families may require a different API or
request schema. Use only synthetic test input and review token costs first.

From the selected lane directory, with `TEST_AZD_ENV` set and the Azure CLI
signed in as the authorized caller:

```bash
set -euo pipefail
account=$(azd env get-value AZURE_AI_ACCOUNT_NAME --environment "$TEST_AZD_ENV")
model=$(azd env get-value AZURE_AI_MODEL_DEPLOYMENT_NAME --environment "$TEST_AZD_ENV")
body=$(jq -cn --arg model "$model" '{
  model: $model,
  messages: [{role: "user", content: "Reply with a short greeting."}],
  max_completion_tokens: 4096
}')
response=$(az rest --method post \
  --url "https://${account}.openai.azure.com/openai/v1/chat/completions" \
  --resource https://cognitiveservices.azure.com \
  --headers Content-Type=application/json \
  --body "$body")
printf '%s' "$response" | jq -e '
  (.error? == null) and
  (.choices[0].message.content | type == "string" and test("\\S"))
' >/dev/null
printf '%s' "$response" | jq -r '.choices[0].message.content'
```

Success requires both a successful HTTP request and nonempty model text. A
resource ID, an accepted deployment or an empty response is not an inference
result. Reasoning models can consume the output allowance before producing
visible text; inspect the response and model guidance before changing the limit.
Do not retry indefinitely or silently treat errors as success.

For `401` or `403`, check the caller, token audience and role scope. For `404`,
check the endpoint, deployment name and supported API. For `429`, check quota,
rate limits and model capacity. For DNS or timeout failures, check the client's
DNS resolution, outbound HTTPS access and proxy settings. Do not bypass TLS checks.

When finished, follow the [cleanup instructions](../README.md#cleanup) and your
lane's additional notes. No agent outbound test is possible in Core because no
agent is deployed.