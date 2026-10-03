# Chat Completions sample

This directory contains the level 00a Python client. It sends one prompt to the
model deployed by `00a-foundry-core-public` and prints the first returned
message. It does not deploy an application, store conversation state, or use
API keys.

For a detailed walkthrough of the implementation, see
[How `chat_completions.py` works](chat_completions-explained.md).

## Prerequisites

1. Bootstrap and provision scenario `00a`.
2. Grant the caller `Cognitive Services OpenAI User` on the Foundry resource
   and wait for the assignment to propagate.
3. Sign in with Azure CLI as that authorized user.
4. Install Python 3.10 or later.

The sample reads the scenario binding, `AZURE_AI_ACCOUNT_NAME`, and
`AZURE_AI_MODEL_DEPLOYMENT_NAME` from the selected azd environment. It rejects
environments that do not belong to lane `00a`.

## Run

From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python chat_completions.py \
  --environment <00a-azd-environment-name> \
  "Reply with exactly: Hello from Foundry."
```

Use only synthetic prompts until the workload's data handling requirements are
approved. Model calls can incur charges.

The client uses the signed-in Azure CLI user through `AzureCliCredential` and
the `https://ai.azure.com/.default` token scope. It calls:

```text
https://<account>.services.ai.azure.com/openai/v1/
```

If authentication succeeds but authorization fails, verify the caller's role
assignment. If environment loading fails, confirm the environment name from
`../00a-foundry-core-public` with `azd env list`.

## Test

The unit tests mock azd, identity, and model access; they do not call Azure:

```bash
python -m unittest -v test_chat_completions.py
```
