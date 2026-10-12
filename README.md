# Microsoft Foundry Notes

Independently deployable learning scenarios for **Microsoft Foundry (new)**.
Editorial content is published only on LinkedIn and is not stored in this
repository.

## Included scenarios

| Lane | Configuration | Primary purpose |
| --- | --- | --- |
| [00a Public](scenarios/00-foundry-core/00a-foundry-core-public/README.md) | Public Foundry endpoint with Entra ID authentication | Chat Completions and the ten-document model benchmark |
| [00c BYO VNet](scenarios/00-foundry-core/00c-foundry-core-byo-vnet/README.md) | Private Foundry endpoint in a customer-managed VNet, reached through API Management Developer | Private networking and gateway validation |

Each lane provisions its own resources and can be deployed independently. No
agent, retrieval system, business-data source, VPN, or Bastion host is included.

## LinkedIn publication packages

The repository contains the reproducible technical material for three articles
scheduled this week. Article text, covers, diagrams, and LinkedIn post copy are
intentionally excluded from Git and are published only through LinkedIn.

| Article | Technical material in this repository |
| --- | --- |
| Private by Design, Reachable by Gateway | Lane 00c, private endpoint, private DNS, API Management Developer, and static/live verification |
| 00c Chat Completions — One Blocked Call, One Policy, One Response | Shared Python client, direct negative test, separate APIM policy, and gateway path |
| 00a Model Benchmark — Valid JSON, Wrong Priority | Lane 00a `gpt-4.1-mini`, ten synthetic labeled documents, strict JSON output, and native Foundry Evaluation graders |

The public repository is the technical companion for the LinkedIn articles:
use the lane READMEs and the application guide for reproduction. Do not add an
`articles/` directory or editorial assets here; the root `.gitignore` protects
that boundary.

## Prerequisites

- Bash on Linux, macOS or WSL, standard shell utilities, `jq`, and Git.
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli),
  [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd),
  and Bicep through Azure CLI.
- An Azure subscription with the required resource-creation and role-assignment
  permissions, registered providers, regional model availability, and quota.
- For lane 00c, API Management Developer capacity and the Entra object IDs of
  the intended gateway callers.

Review Azure pricing and organizational policy before provisioning. The
templates are learning assets, not production-ready or compliance-certified
systems. Use synthetic data for the included tests.

## Configure and deploy

Clone the complete repository because both lanes depend on shared modules and
scripts:

```bash
git clone https://github.com/gderossilive/msfoundrynotes.git
cd msfoundrynotes
chmod +x scripts/*.sh scenarios/*/*/test/test-scenario.sh
cp .env.example .env
```

Set the tenant, subscription, region, and environment name in the ignored
`.env`. Lane 00c also requires the API Management publisher contact and a JSON
array of allowed Entra object IDs. Do not add keys, tokens, passwords,
certificates, or connection strings.

Sign in to Azure CLI and Azure Developer CLI, then deploy exactly one lane:

```bash
lane=00-foundry-core/00a-foundry-core-public
# Or: lane=00-foundry-core/00c-foundry-core-byo-vnet
bash scripts/bootstrap-scenario-env.sh "$lane"
cd "scenarios/$lane"
azd provision --environment "$AZURE_ENV_NAME"
```

Bootstrap binds the azd environment to one lane and creates or selects its
resource group. It applies the lab tag `SecurityControl=Ignore`; this is not an
Azure Policy exemption and must be reviewed with the policy owner.

## Test

Run all local static checks without provisioning:

```bash
bash scripts/test-all-scenarios.sh --static
```

The checks compile both lanes, validate the separate 00c API Management policy,
exercise mocked bootstrap behavior, and run the scenario contracts. The Python
unit tests mock Azure access:

```bash
cd scenarios/00-foundry-core/app
python -m unittest -v test_chat_completions.py test_benchmark_documents.py
```

See [Testing and inference](docs/testing.md) for live checks and the
[application guide](scenarios/00-foundry-core/app/README.md) for Chat
Completions and the document benchmark.

## Cleanup

From the selected lane directory, verify the environment and resource group,
then remove the deployment:

```bash
azd env get-value AZURE_RESOURCE_GROUP --environment "$AZURE_ENV_NAME"
azd down --environment "$AZURE_ENV_NAME" --force --purge
```

Confirm the resource group is gone. Lane 00c includes an always-on API
Management Developer instance that remains billable until deleted.

## Layout

```text
scenarios/00-foundry-core/      Level 00 lanes and shared Python application
modules/                        Shared Foundry, network, and gateway modules
scripts/                        Bootstrap, policy, metadata, and test helpers
docs/testing.md                 Static, live, and inference guidance
```

Technical names containing `FoundryLab` are retained to preserve the deployment
and test contracts. Local environment state, private memory, credentials,
editorial content, and the source repository history are excluded.

## License

Licensed under the [MIT License](LICENSE).
