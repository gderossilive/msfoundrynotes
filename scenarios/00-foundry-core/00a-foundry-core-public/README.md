# Level 00, lane 00a: Foundry Core public

This lane creates a Microsoft Foundry account, a project, and one model deployment. It is the
smallest independent foundation in Microsoft Foundry Notes. To read its template step by step, see the
Optional companions add [model monitoring](../app/monitor_model-explained.md)
and a [public gateway](../app/public_gateway-explained.md), without creating another lane. To read its template step by step, see the
[Bicep learning guide](infra/main.md). The episodes that use this lane are listed in the
[repository README](../../../README.md#published-episodes).

## Prerequisites

- Permission to create a resource group and its resources: bootstrap creates the lane
  resource group if it does not exist.
- Azure CLI authenticated as the human user who will invoke the model.
- Permission to assign roles: provisioning grants that user the inference and fine-tuning roles.
- Model quota for the selected model, SKU, capacity, and region.
- Azure CLI, Azure Developer CLI, Bicep CLI, Bash, Git and `jq`.

## Deploy

From the repository root, prepare the lane-local azd environment from the ignored root `.env`:

```bash
scripts/bootstrap-scenario-env.sh 00-foundry-core/00a-foundry-core-public
```

Bootstrap preserves the instance token already stored in the selected azd environment. To prepare
a separate resource group and azd environment, run `scripts/bootstrap-scenario-env.sh
00-foundry-core/00a-foundry-core-public --new-instance`.

Then deploy from this directory with `.env` loaded:

```bash
azd provision --environment "$AZURE_ENV_NAME"
```

If bootstrap used `--new-instance`, pass that new environment name instead.

To remove the lane resource group, confirm the target first, then delete it:

```bash
azd env get-value AZURE_RESOURCE_GROUP --environment "$AZURE_ENV_NAME"
azd down --environment "$AZURE_ENV_NAME" --force --purge
```

## Outputs

- Foundry account and project resource IDs
- Project managed identity principal ID
- Model deployment name

## Deployed Resources

This lane deploys only the minimum Microsoft Foundry foundation in the target resource group:

- A Microsoft Foundry account (`Microsoft.CognitiveServices/accounts`) with the `AIServices` kind and `S0` SKU.
- A Microsoft Foundry project (`Microsoft.CognitiveServices/accounts/projects`) in that account.
- One Azure OpenAI model deployment (`Microsoft.CognitiveServices/accounts/deployments`).
- System-assigned managed identities for the Foundry account and project.
- An account-scoped `Cognitive Services OpenAI User` assignment for the human Azure CLI deployer.
- A project-scoped `Foundry Owner` assignment for that deployer to run cloud evaluations,
  fine-tune the model, and deploy the resulting checkpoint.

Foundry Owner is broader than the benchmark-only Foundry User role in earlier
versions. Review this project-scoped permission before provisioning. Existing
deployments need this role (directly or inherited) for checkpoint deployment;
reprovisioning adds it but does not remove earlier role assignments.

The account is configured with public network access and local authentication disabled, so callers use
Microsoft Entra ID rather than account keys. Bootstrap binds the signed-in user's object ID to the azd
environment, and provisioning grants that user model inference access. The project is created before
the model deployment because Azure AI Services does not allow concurrent operations on the same account.

The 00a model and version are lane-specific: bootstrap selects them independently of the
ignored root `.env`, which may still configure other lanes. SKU and capacity continue to
come from `.env`. The current development values are:

- Model: `gpt-4.1-mini`
- Version: `2025-04-14`
- SKU: `GlobalStandard`
- Capacity: `30` (30K TPM)

The default profile does not deploy agents, application code, Azure AI Search, Storage, Cosmos DB,
Application Insights, Key Vault, API Management, virtual networks, private endpoints, or private DNS.

## Optional model monitoring

The [Italian monitoring walkthrough](../app/monitor_model-explained.md) explains
platform metrics, ten bounded synthetic requests, content-free client spans and
native quality/safety evaluation. No agent is created. Metrics alone need no
additional telemetry resources.

For separately authorized tracing and diagnostics, from this lane directory:

```bash
environment=<your-00a-azd-environment>
azd env set AZURE_ENABLE_MONITORING true --environment "$environment"
azd provision --environment "$environment"
```

The opt-in profile creates Log Analytics (30-day retention), Entra-authenticated
Application Insights, an AppInsights connection, selective `Audit`/`RequestResponse`
diagnostics and scoped monitoring roles. Outputs include
`AZURE_MONITORING_ENABLED`, `AZURE_MONITORING_WORKSPACE_ID` and
`AZURE_MONITORING_APPLICATION_INSIGHTS_ID`.

From the [application directory](../app/README.md#model-monitoring-00a), install
the optional requirements and explicitly request tracing/evaluation:

```bash
python -m pip install -r requirements-monitoring.txt
python monitor_model.py --environment "$environment" --trace --evaluate --evaluate-safety
```

On 2026-11-01 in Sweden Central, ten calls and all ten client spans were
verified; client/platform token totals matched. Resource diagnostics and RAI
metrics returned no rows/series despite configuration. This is no-data, not
zero defects. The guide records historical evidence and unverified portal
surfaces. Setting monitoring back to false does not delete prior resources or
stop charges; cleanup is separate and target-specific.

## Optional public gateway (API Management Basic v2)

The [Italian Public Gateway walkthrough](../app/public_gateway-explained.md)
explains an opt-in Basic v2 gateway with the same policy modules as 00c.
It creates no VNet, new lane or agent.

**An extra door, not the only one:** Foundry remains public and the deployer
keeps its direct inference role. Direct calls still work, bypass the APIM
budget and do not appear in its per-caller metric. This profile demonstrates
that boundary; it does not enforce gateway-only access.

From the lane directory, configure the allowlist and enable the gateway:

```bash
environment=<your-00a-azd-environment>
azd env set AZURE_ENABLE_GATEWAY true --environment "$environment"
azd env set AZURE_APIM_ALLOWED_PRINCIPAL_IDS '["<caller-object-id>"]' --environment "$environment"
azd provision --environment "$environment"
```

**Provisioning does not apply the API policy.** A gateway response before
policy application was observed in the lab; do not assume deny-all at that
stage. Apply the policy immediately from the repository root:

```bash
scripts/apply-gateway-policy.sh 00a "$environment"
```

`AZURE_GATEWAY_APIM_SKU` defaults to `BasicV2`; `StandardV2` is also accepted.
The outputs are `AZURE_GATEWAY_ENABLED`, `AZURE_APIM_ID`, `AZURE_APIM_NAME`,
`AZURE_APIM_PRINCIPAL_ID` and `AZURE_APIM_CHAT_COMPLETIONS_ENDPOINT`.
The API validates Entra tokens and the object-ID allowlist (`[]` denies all).
The gateway's managed identity reaches Foundry with its own account-level
inference role. API Management is billed while it exists, including when idle.

Optional `AZURE_APIM_TOKENS_PER_MINUTE` (default `0`) and
`AZURE_APIM_USAGE_METRICS` (default `false`) are applied by the same policy
command, not by foundation provisioning. The [token demo](../app/token_limit_demo-explained.md)
and [usage report](../app/usage_report-explained.md) accept `--scenario 00a`.
Metric resources are supporting code for the bypass check, not a separately
published Usage Attribution episode.

On 2026-11-02 in Italy North, Basic v2 direct/gateway calls both succeeded,
per-caller budgets and recovery were observed with 120 tokens/min, and two
direct calls produced a model-minus-gateway difference of 28 input and 6 output
tokens. The lab and second caller were removed. Streaming, Standard v2,
multiple instances and a model-side 429 were not exercised.

## Call the deployed model

The level-owned [Python Chat Completions sample](../app/README.md) requires this lane to be
successfully provisioned. Capture the selected environment, then run the local client:

```bash
environment=$(azd env get-value FOUNDRY_AZD_ENVIRONMENT)
cd ../app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python chat_completions.py --environment "$environment" "Reply with exactly: Hello from Foundry."
```

The sample deploys no application resource and stores no API key. If the first call receives an
authorization error, allow time for the new role assignment to propagate.

To benchmark document classification quality on ten labeled synthetic examples, use the
[level-owned benchmark CLI](../app/README.md#document-classification-benchmark-00a).
It calls this lane's deployed model and evaluates labels with Microsoft Foundry
Evaluation. For an existing deployment, verify the caller already has the
project role (possibly inherited), or reprovision this lane to apply it. It
does not create an Azure application resource, but each evaluation creates a
run in the Foundry project.

To continue the benchmark with supervised fine-tuning, use the
[document fine-tuning workflow](../app/README.md#document-classification-fine-tuning-00a).
It keeps the ten benchmark documents out of training, submits a Developer-tier
job, evaluates three checkpoints, and retains the selected fine-tuned deployment.
Training, checkpoint deployments, inference, and evaluations are separate,
explicit commands and can incur charges. No fine-tuning job is created by
provisioning this lane.
