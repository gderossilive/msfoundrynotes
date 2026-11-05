# Microsoft Foundry Notes

Independently deployable learning scenarios for **Microsoft Foundry (new)**.
Editorial content is published only on LinkedIn and is not stored in this
repository.

## Included scenarios

A **scenario** (or **lane**) is the infrastructure you deploy: a Bicep template,
a bootstrap step and tests that provision one Foundry configuration. This
repository contains two lanes, and each can be deployed on its own. Deploy
exactly one to follow the repository; the lane's README is the entry point.

| Lane | Configuration | Primary purpose |
| --- | --- | --- |
| [00a Public](scenarios/00-foundry-core/00a-foundry-core-public/README.md) | Public Foundry endpoint with Entra ID authentication | Chat Completions, the ten-document model benchmark, and supervised fine-tuning |
| [00c BYO VNet](scenarios/00-foundry-core/00c-foundry-core-byo-vnet/README.md) | Private Foundry endpoint in a customer-managed VNet, reached through API Management Developer | Private networking and gateway validation |

Each lane provisions its own resources and can be deployed independently. No
agent, retrieval system, business-data source, VPN, or Bastion host is included.
The lanes are listed above once; the episodes below build on them.

## Published episodes

An **episode** is a LinkedIn article that explains one step of the series. It
does not add a new deployment: every episode runs on top of a lane above, either
by deploying that lane or by running a local client or test against it. Several
episodes can share the same lane (00a has three, 00c has two), and an episode
may need only the code that runs against a lane you already deployed.

Each article is published only on LinkedIn. This repository holds the
reproducible technical material for it; the **Lane** column tells you which
scenario to deploy first, and the other columns link to the guide and the exact
version the article was written against.

| Episode | Lane | LinkedIn article | Technical material on `main` | Pinned version |
| --- | --- | --- | --- | --- |
| 00a Foundry Core — Three Resources, One Model, No Agent Yet | 00a | [Read on LinkedIn](https://www.linkedin.com/pulse/microsoft-foundry-notes-three-resources-one-model-agent-de-rossi-srsde/) | [Lane README](scenarios/00-foundry-core/00a-foundry-core-public/README.md) and [Bicep guide](scenarios/00-foundry-core/00a-foundry-core-public/infra/main.md) | [`episode-00a-foundry-core-v1.0.0`](https://github.com/gderossilive/msfoundrynotes/releases/tag/episode-00a-foundry-core-v1.0.0) |
| 00a Chat Completions — One Prompt, One Role, One Response | 00a | [Read on LinkedIn](https://www.linkedin.com/pulse/microsoft-foundry-notes-00a-chat-completions-one-prompt-de-rossi-kifbe/) | [Chat Completions client](scenarios/00-foundry-core/app/README.md#run) and [script walkthrough](scenarios/00-foundry-core/app/chat_completions-explained.md) | [`episode-00a-chat-completions-v1.0.0`](https://github.com/gderossilive/msfoundrynotes/releases/tag/episode-00a-chat-completions-v1.0.0) |
| 00c Foundry Core — Private by Design, Reachable by Gateway | 00c | [Read on LinkedIn](https://www.linkedin.com/pulse/private-design-reachable-gateway-gianluca-de-rossi-owy8e/) | [Lane README](scenarios/00-foundry-core/00c-foundry-core-byo-vnet/README.md) and [private Foundry module guide](modules/core/private-foundry-scenario/main.md) | [`episode-00c-foundry-core-byo-vnet-v1.0.0`](https://github.com/gderossilive/msfoundrynotes/releases/tag/episode-00c-foundry-core-byo-vnet-v1.0.0) |
| 00c Chat Completions — One Blocked Call, One Policy, One Response | 00c | [Read on LinkedIn](https://www.linkedin.com/pulse/microsoft-foundry-notes-00c-chat-completions-one-blocked-de-rossi-gwlve/) | [Direct test, APIM policy and gateway test](scenarios/00-foundry-core/00c-foundry-core-byo-vnet/README.md#verify) with the [shared client](scenarios/00-foundry-core/app/README.md#run) | [`episode-00c-chat-completions-v1.0.0`](https://github.com/gderossilive/msfoundrynotes/releases/tag/episode-00c-chat-completions-v1.0.0) |
| 00a Model Benchmark — Valid JSON, Wrong Priority | 00a | [Read on LinkedIn](https://www.linkedin.com/pulse/microsoft-foundry-notes-00a-model-benchmark-valid-json-de-rossi-qpuwf/) | [Ten-document benchmark](scenarios/00-foundry-core/app/README.md#document-classification-benchmark-00a) with Foundry Evaluation graders and a [script walkthrough](scenarios/00-foundry-core/app/benchmark_documents-explained.md) | [`episode-00a-model-benchmark-v1.0.0`](https://github.com/gderossilive/msfoundrynotes/releases/tag/episode-00a-model-benchmark-v1.0.0) |
| 00a Model Fine-Tuning — 60% to 100%, Still Not Production | 00a | [Read on LinkedIn](https://www.linkedin.com/pulse/microsoft-foundry-notes-00a-model-fine-tuning-60-100-still-de-rossi-wkhwf/) | [Fine-tuning guide](scenarios/00-foundry-core/app/README.md#document-classification-fine-tuning-00a) and [script walkthrough](scenarios/00-foundry-core/app/fine_tune_documents-explained.md) | [`episode-00a-model-fine-tuning-v1.0.1`](https://github.com/gderossilive/msfoundrynotes/releases/tag/episode-00a-model-fine-tuning-v1.0.1) |

`main` always contains the current source. A pinned version is the exact source
the article was written against; use it to reproduce the article's results.
Versions pinned before the fine-tuning release predate the broader project role
described below. Do not add an `articles/` directory or editorial assets here; the root
`.gitignore` protects that boundary.

**Lane 00a permissions and costs.** Current 00a provisioning grants the human
deployer **Foundry Owner at project scope**, needed to deploy fine-tuned
checkpoints, and **Cognitive Services OpenAI User at account scope** for
inference. This is broader than the earlier benchmark-only Foundry User role;
review it before provisioning. Fine-tuning, checkpoint deployments, and
evaluations are separate explicit commands and can incur charges. Nothing is
trained by provisioning or by the local tests.

## Episode plan

The diagram shows the level 00 episodes by lane, in editorial order: what is
already published on LinkedIn, what has a pinned release waiting for its
article, and what is still a draft. It is a plan, not a schedule: publication
dates are not committed and the order can change. A draft episode has no
technical companion or pinned version in this repository yet; both appear here
when its article is published.

![Level 00 episode plan. Lane 00a has seven episodes: Foundry Core, Chat Completions, Model Benchmark and Model Fine-Tuning are published, while Model Monitoring, Managed Compute and Public Gateway are drafts. Lane 00c has four: Foundry Core BYO VNet and Chat Completions are published, Token Governance and Usage Attribution are drafts. Lane 00b has no episode yet. Public Gateway on 00a reuses the shared APIM policy module of 00c.](docs/images/level-00-episodes-map.png)

The diagram is also available as an editable
[SVG](docs/images/level-00-episodes-map.svg).

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

Lane 00a bootstrap pins its own model, `gpt-4.1-mini` (`2025-04-14`), regardless of
the model values in `.env`; SKU and capacity still come from `.env`. Lane 00c uses
the `.env` model values. After provisioning lane 00c, its API Management policy is
applied as a separate step: follow the [lane README](scenarios/00-foundry-core/00c-foundry-core-byo-vnet/README.md#verify).

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
python -m unittest -v \
  test_chat_completions.py \
  test_benchmark_documents.py \
  test_prepare_finetuning_data.py \
  test_fine_tune_documents.py
```

See [Testing and inference](docs/testing.md) for live checks and the
[application guide](scenarios/00-foundry-core/app/README.md) for Chat
Completions, the document benchmark, and supervised fine-tuning.

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
  00a-foundry-core-public/      Public lane, with a Bicep learning guide in infra/main.md
  00c-foundry-core-byo-vnet/    Private lane with API Management gateway
  app/                          Chat Completions, benchmark, and fine-tuning clients,
                                with script walkthroughs (*-explained.md)
  data/                         Synthetic 100-document source
modules/                        Shared Foundry, network, and gateway modules
scripts/                        Bootstrap, policy, metadata, and test helpers
docs/testing.md                 Static, live, and inference guidance
docs/images/                    Level 00 episode plan diagram (SVG and PNG)
```

Technical names containing `FoundryLab` are retained to preserve the deployment
and test contracts. Local environment state, private memory, credentials,
editorial content, and the source repository history are excluded.

## License

Licensed under the [MIT License](LICENSE).
