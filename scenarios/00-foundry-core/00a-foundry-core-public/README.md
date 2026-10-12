# Level 00, lane 00a: Foundry Core public

This lane creates a Microsoft Foundry account, a project, and one model deployment. It is the
smallest independent foundation in Microsoft Foundry Notes.

## Prerequisites

- Permission to create a resource group and its resources: bootstrap creates the lane
  resource group if it does not exist.
- Azure CLI authenticated as the human user who will invoke the model.
- Permission to assign roles: provisioning grants that user the inference and evaluation roles.
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
- A project-scoped `Foundry User` assignment for that deployer to run cloud evaluations.

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

This lane does not deploy agents, application code, Azure AI Search, Storage, Cosmos DB,
Application Insights, Key Vault, API Management, virtual networks, private endpoints, or private DNS.

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

Read the [Foundry Core article](../../../articles/published/episode-00a-foundry-core.md) for the architectural
foundation and [the Chat Completions article](../../../articles/published/episode-00a-chat-completions.md) for
the authenticated application flow.