# Level 00, lane 00a: Foundry Core public

This lane creates a Microsoft Foundry account, a project, and one model deployment. It is the
smallest independent foundation in the FoundryLab catalog.

## Prerequisites

- Permission to create AI Services resources in the target resource group.
- Model quota for the selected model, SKU, capacity, and region.
- Azure CLI, Azure Developer CLI, Bicep CLI and Bash. See the
	[repository setup](../../../README.md#prerequisites) before provisioning.

## Deploy

From the repository root, prepare the lane-local azd environment from the ignored root `.env`:

```bash
scripts/bootstrap-scenario-env.sh 00-foundry-core/00a-foundry-core-public
```

Bootstrap preserves the instance token already stored in the selected azd environment. To prepare
a separate resource group and azd environment, run `scripts/bootstrap-scenario-env.sh
00-foundry-core/00a-foundry-core-public --new-instance`.

Then deploy from this directory:

```bash
azd provision
```

Use `azd down --force --purge` to remove the lane resource group when it is no longer needed.

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