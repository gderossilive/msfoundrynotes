# Chat Completions sample

This directory contains the shared level 00 Python sample. It sends one prompt to the model
deployed by `00a-foundry-core-public` or `00c-foundry-core-byo-vnet` and prints the first returned
message. It does not deploy an application, store conversation state, or support API keys.

## Prerequisites

1. Bootstrap and provision scenario `00a` or `00c`.
2. For `00a`, wait for the deployer's `Cognitive Services OpenAI User` role assignment to propagate.
   For `00c`, add the caller object ID to `AZURE_APIM_ALLOWED_PRINCIPAL_IDS` and apply the separate
   APIM policy after provisioning.
3. Sign in with Azure CLI as the authorized human user.
4. Install Python 3.10 or later.

The sample reads the scenario binding, `AZURE_AI_ACCOUNT_NAME`, and
`AZURE_AI_MODEL_DEPLOYMENT_NAME` from the selected azd environment. For `00c` it also requires
`AZURE_APIM_CHAT_COMPLETIONS_ENDPOINT`. It rejects all other scenarios.

## Run

From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python chat_completions.py --environment <azd-environment-name> "Reply with exactly: Hello from Foundry."
```

The command above preserves the existing 00a behavior: `--scenario` defaults to `00a`. azd environments
are scenario-local, so select scenario 00c explicitly. Its default `direct` target intentionally calls the
private Foundry endpoint and should fail from an external machine:

```bash
python chat_completions.py --environment <00c-azd-environment-name> --scenario 00c "Reply with exactly: Hello from Foundry."
```

After applying the APIM policy, route the same app through the gateway:

```bash
python chat_completions.py --environment <00c-azd-environment-name> --scenario 00c --target gateway "Reply with exactly: Hello from Foundry."
```

Use only synthetic prompts until the workload's data handling requirements are approved. Model calls
can incur charges.

The client uses the signed-in Azure CLI user through `AzureCliCredential` and the
`https://ai.azure.com/.default` token scope. For 00a and the direct 00c test it uses:

```text
https://<account>.services.ai.azure.com/openai/v1/
```

For the 00c gateway test it instead uses `https://<apim>.azure-api.net/openai/v1/`. APIM validates
the caller token and allowlist, then replaces the backend authorization with its managed identity.

If authentication succeeds but authorization fails, verify the 00a deployer role or the 00c gateway
allowlist and policy. If environment loading fails, confirm the environment name from the lane
directory with `azd env list`.

## Test

The unit tests mock azd, identity, and model access; they do not call Azure:

```bash
python -m unittest -v test_chat_completions.py test_benchmark_documents.py
```

## Document classification benchmark (00a)

The separate `benchmark_documents.py` command measures classification quality against ten
synthetic business documents in [data/business_documents_10.json](data/business_documents_10.json),
selected in source order from the provided set of 100. All six document types are represented
(four types twice and two types once). The labels `document_type`, `department` and `priority`
are the expected answers. The command uses the same Azure CLI identity and model deployment
as the Chat Completions sample, plus the Microsoft Foundry project's cloud evaluation API.
No custom evaluator or hosted application is deployed.

This benchmark is the reproducible technical companion for the LinkedIn article
**00a Model Benchmark — Valid JSON, Wrong Priority**. The article and its
publication assets are not stored in this repository.

Scenario 00a deployments from this release assign the Azure CLI deployer
**Foundry User** on the project, in addition to **Cognitive Services OpenAI User**
on the account. For an existing deployment, check that the caller already has
Foundry User on the project (directly or inherited); otherwise reprovision with
role-assignment permissions and wait for propagation. The earlier Foundry Core
v1.0.0 release does not include this change. With an authorized 00a azd
environment, run from this directory:

```bash
python benchmark_documents.py --environment <00a-azd-environment-name>
```

The command first sends one Chat Completions request per document using a strict JSON Schema.
It passes the valid predicted and reference labels, **not the document text**, as a small
inline dataset to Microsoft Foundry Evaluation. Four built-in `string_check` graders
(`eq`) calculate exact-match accuracy for each field and all three together. Foundry
retains the evaluation and run; the terminal shows its accuracy and report URL.
The ignored local `benchmark-results.json` records the evaluation/run IDs, coverage,
accuracy returned by Foundry and per-document labels or errors. `--output <path>`
selects another report destination. Do not publish reports containing data your
organization considers sensitive; the labels are sent to and stored in Foundry.

Allowed labels come from the fixture. Invalid, incomplete, refused or truncated model
responses are recorded as errors and omitted from the Foundry evaluation dataset.
**Coverage** is the valid response count divided by all documents. Each **accuracy**
is the Foundry grader's pass rate among valid responses; inspect coverage alongside
accuracy. If none are valid, the local report records every error and `null` accuracies,
no cloud evaluation runs, and the command exits nonzero. Authentication, API and
evaluation-run failures also exit nonzero without writing a misleading success report.
Repeated runs can produce different answers. These ten examples provide a small smoke
benchmark, not a statistically representative quality estimate. Model calls and
cloud evaluations may incur charges; unit tests use mocks and do not call Azure.

On 2026-10-02, one live 00a Foundry Evaluation run completed with 10 valid responses
and exact-match rates of 100% type, 80% department, 60% priority and 50% all fields.
These aggregate rates matched an earlier locally scored run, but the priority
error moved between two contract documents. Repeat runs and inspect item-level
results before interpreting small changes as an improvement.

On 2026-10-02, after changing 00a to `gpt-4.1-mini` (`2025-04-14`),
another Foundry Evaluation run on the same ten items returned 10/10 valid,
100% type, 100% department, 60% priority and 60% all-fields accuracy. Its
separate ignored report is `benchmark-foundry-gpt-4.1-mini-results.json`.
The 10-point difference on department and all-fields is one document each;
this tiny, variable sample cannot establish that the new model is better.
Keep these ten documents out of fine-tuning data for the before/after comparison.
