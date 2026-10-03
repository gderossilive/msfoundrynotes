# Microsoft Foundry Notes

Independently deployable learning scenarios for **Microsoft Foundry (new)**.
This source publication contains **scenario 00: Microsoft Foundry Core**,
with the **00a public variant** and its deployment and testing dependencies.
It does not publish the editorial drafts or the rest of the scenario catalog.

## Included variant

| Lane | Configuration | Validation boundary |
| --- | --- | --- |
| [00a Public](scenarios/00-foundry-core/00a-foundry-core-public/README.md) | Foundry resource, project and model deployment; public endpoint; Entra ID authentication | Static tests included; run live checks and inference in your environment |

The public variant provisions its own resources and requires no other scenario
to be deployed. It creates no agent, application, VNet, private endpoint, client
VM, VPN or Bastion.

## Prerequisites

- Bash on Linux, macOS or WSL, standard shell utilities, `jq`, and Git.
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli),
  [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
  and the [Bicep CLI](https://learn.microsoft.com/azure/azure-resource-manager/bicep/install)
  available through Azure CLI. Use current versions that support Bicep parameter files.
- An Azure subscription, permission to create the selected resources and any
  required role assignments, registered resource providers, and sufficient model
  quota.
- A model version and deployment type supported in the chosen region. The sample
  defaults are `gpt-5-mini`, version `2025-08-07`, `GlobalStandard`, capacity `30`.
  These are configurable examples, not a guarantee of availability. Global
  deployments do not guarantee inference processing in the resource's region.

Review pricing and organizational policy before provisioning. Model usage can
incur charges. This is a learning template, not a production-ready or
compliance-certified system. Use synthetic
data for the initial test.

## Deploy the public variant

Clone the complete repository; downloading a single scenario directory omits
shared dependencies. To reproduce a specific revision, check out its commit SHA.

```bash
git clone https://github.com/gderossilive/msfoundrynotes.git
cd msfoundrynotes
chmod +x scripts/*.sh scenarios/*/*/test/test-scenario.sh
[[ -f .env ]] || cp .env.example .env
```

Edit the local `.env`: set your tenant ID, subscription ID, location, environment
name and model settings. Change the model name and version together. Keep this
file uncommitted; never put credentials, keys, tokens or connection strings in it.
The file is sourced as Bash, so only use trusted content.

Sign in to both CLIs and select the intended subscription. Run these commands
from the repository root after configuring `.env`:

```bash
set -a
source .env
set +a
az login --tenant "$AZURE_TENANT_ID"
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
azd auth login --tenant-id "$AZURE_TENANT_ID"
```

Deploy the public lane:

```bash
lane=00-foundry-core/00a-foundry-core-public
bash scripts/bootstrap-scenario-env.sh "$lane"
cd "scenarios/$lane"
azd provision --environment "$AZURE_ENV_NAME"
```

Bootstrap creates or selects a lane-local azd environment, creates its resource
group if needed, and sets `SecurityControl=Ignore` on that group. **This tag is
not itself an Azure Policy exemption.** Review its effect with your policy owner
before running bootstrap. `--new-instance` creates a separate environment and
resource group; use the resulting environment name for provision, tests and cleanup.

The public lane disables key-based authentication. Resource creation permissions are
not inference permissions: the caller needs its own authorized Entra identity.
The template does not assign an inference role to the deploying user.

## Test

Local static checks require Azure CLI/Bicep and `jq`, but no Azure deployment:

```bash
bash scripts/test-all-scenarios.sh --static
```

This runs the included bootstrap and metadata mocks, then the 00a Core lane
suite. Shared helper fixtures exercise additional naming and input-validation
cases; they do not require other scenarios to be present or deploy them.

Follow [Testing and inference](docs/testing.md) for parameter compilation,
explicit-environment live checks and caller permissions. Use the
[Chat Completions sample](scenarios/00-foundry-core/app/README.md) for a
keyless inference request. The lane wrapper does not implement Core `--e2e`
automation.

Static compilation is not proof of successful provisioning or inference.

## Cleanup

From the selected lane directory, verify the target environment before deletion:

```bash
azd env get-value AZURE_RESOURCE_GROUP --environment "$AZURE_ENV_NAME"
azd down --environment "$AZURE_ENV_NAME" --force --purge
```

Use the actual environment name if bootstrap used `--new-instance`. This is a
destructive operation: confirm the group contains only that lab's resources.
Read the lane's cleanup notes, verify resources are gone, and review any
soft-deleted Foundry resource. A failed cleanup can leave billable resources.

## Layout

```text
scenarios/00-foundry-core/   Level overview, metadata and the 00a public azd lane
scenarios/00-foundry-core/app/  Keyless Python Chat Completions client and tests
modules/core/              Shared Foundry resource, project and model module
scripts/                   Bootstrap, metadata, security helpers and local tests
docs/testing.md            Live checks and manual keyless inference
.env.example               Non-secret configuration template
LICENSE                    MIT License
```

Technical names containing `FoundryLab` are retained to keep deployment naming
and test contracts consistent with the source templates. No local environment
state, private memory, credentials or source-repository Git history is included.

## License

Licensed under the [MIT License](LICENSE).