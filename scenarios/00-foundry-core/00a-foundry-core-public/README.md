# Level 00, lane 00a: Foundry Core public

This lane creates a Microsoft Foundry account, a project, and one model deployment. It is the
smallest independent foundation in Microsoft Foundry Notes.

For a step-by-step explanation of the infrastructure, read the
[main.bicep learning guide](infra/main.md). It covers parameters, naming,
the shared module, identities, dependencies, outputs, and the caller
permissions that must be assigned separately.

## Prerequisites

- Permission to create a resource group and its resources: bootstrap creates the lane
  resource group if it does not exist.
- Permission to assign roles, or an administrator who can grant the caller's inference role.
- Model quota for the selected model, SKU, capacity, and region.
- Azure CLI, Azure Developer CLI, Bicep CLI, Bash, Git and `jq`. See the
  [repository setup](../../../README.md#prerequisites) before provisioning.

## Deploy

From the repository root, prepare the lane-local azd environment from the ignored root `.env`:

```bash
scripts/bootstrap-scenario-env.sh 00-foundry-core/00a-foundry-core-public
```

Bootstrap preserves the instance token already stored in the selected azd environment. To prepare
a separate resource group and azd environment, run `scripts/bootstrap-scenario-env.sh
00-foundry-core/00a-foundry-core-public --new-instance`.

Then deploy from this directory with `.env` loaded, as described in the
[repository guide](../../../README.md#deploy-the-public-variant):

```bash
azd provision --environment "$AZURE_ENV_NAME"
```

If bootstrap used `--new-instance`, pass that new environment name instead.

To remove the lane resource group, confirm the target first, then delete it:

```bash
azd env get-value AZURE_RESOURCE_GROUP --environment "$AZURE_ENV_NAME"
azd down --environment "$AZURE_ENV_NAME" --force --purge
```

Follow the [repository cleanup notes](../../../README.md#cleanup) and verify that the
resources are gone.

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

The account has public network access enabled and local authentication disabled, so callers use
Microsoft Entra ID rather than account keys. The project is created before the model deployment because
Azure AI Services does not allow concurrent operations on the same account.

The default model configuration comes from `.env.example`, copied to the ignored root `.env`:

- Model: `gpt-5-mini`
- Version: `2025-08-07`
- SKU: `GlobalStandard`
- Capacity: `30` (30K TPM)

This lane does not deploy agents, application code, Azure AI Search, Storage, Cosmos DB,
Application Insights, Key Vault, API Management, virtual networks, private endpoints, or private DNS.

Follow [Testing and inference](../../../docs/testing.md) for static and live checks,
caller authorization and a manual keyless model request. The template does not
grant the deploying user inference permission.