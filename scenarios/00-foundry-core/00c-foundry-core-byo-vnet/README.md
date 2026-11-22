# Level 00, lane 00c: Foundry Core with private inbound access

This independent lane creates a Microsoft Foundry account, project, and model
deployment with public network access and local authentication disabled. A
customer-managed VNet, private endpoint subnet, account private endpoint, and
three linked private DNS zones provide private inbound access. It also creates
an API Management Developer gateway in an external VNet subnet. The gateway is
publicly reachable for the lab, but reaches the private Foundry endpoint from
inside the VNet with its own managed identity.

Here, BYO means customer-managed networking: the template creates the VNet in
your subscription. It does not consume another scenario's deployment or an
existing VNet. Address prefixes can be customized in `infra/main.bicepparam`.
For a resource-by-resource walkthrough of the reusable private foundation, see
[Private Microsoft Foundry scenario](../../../modules/core/private-foundry-scenario/main.md).

The initial deployment creates the API, backend, managed identity, and backend
role assignment, but deliberately does not attach its forwarding policy. Apply
the policy only after observing the expected failure of a direct external call
to Foundry. This makes the boundary visible without exposing Foundry itself.

No agent, capability host, agent subnet delegation, managed outbound network,
search, storage, telemetry, VM, VPN, or Bastion is provisioned. In particular,
private inbound access and the APIM gateway do not demonstrate agent outbound
isolation.
The [Italian Token Governance walkthrough](../app/token_limit_demo-explained.md)
adds an optional per-caller budget on this existing gateway.
The [Italian Usage Attribution walkthrough](../app/usage_report-explained.md)
adds optional telemetry and reconciles token usage per caller.

## Prerequisites

- Azure CLI, Azure Developer CLI, and Bicep CLI.
- Permission to create Foundry, API Management, networking resources and role
  assignments, link private DNS zones, and approve the account's private endpoint
  connection.
- Availability and quota for your model, version, SKU, capacity, and region.
- API Management Developer capacity and budget. Developer is an always-on
  development tier and is not production-ready.
- An Entra object ID for every intended gateway caller. Add those IDs to
  `AZURE_APIM_ALLOWED_PRINCIPAL_IDS` in the ignored root `.env`; `[]` denies all
  callers.
- The publisher email and name in `.env`, recorded on the API Management service.

## Deploy

From the repository root, copy `.env.example` to the ignored `.env`, set the
non-secret deployment values, including the APIM publisher contact and allowlist,
and prepare this lane's environment:

```bash
AZURE_APIM_PUBLISHER_EMAIL="platform-team@contoso.com"
AZURE_APIM_PUBLISHER_NAME="Contoso platform team"
AZURE_APIM_ALLOWED_PRINCIPAL_IDS='["<authorized-entra-object-id>"]'
scripts/bootstrap-scenario-env.sh 00-foundry-core/00c-foundry-core-byo-vnet
cd scenarios/00-foundry-core/00c-foundry-core-byo-vnet
azd provision
```

Review the bootstrap lab tag `SecurityControl=Ignore` with your policy owner; it
is not an Azure Policy exemption. Review model, private endpoint, and API
Management Developer costs before provisioning.

## Verify

The template outputs the account/project IDs and names, project identity
principal ID, model deployment name, VNet ID, private endpoint subnet ID and
private endpoint ID. It also outputs the API Management resource, principal,
subnet, and Chat Completions endpoint.

1. Confirm provisioning succeeded, public network access is `Disabled`, and
   `disableLocalAuth` is `true`.
2. Confirm the private endpoint connection is `Approved` and its DNS zone group
   contains `privatelink.cognitiveservices.azure.com`,
   `privatelink.openai.azure.com`, and `privatelink.services.ai.azure.com`.
3. Confirm API Management uses the Developer SKU and `External` VNet mode; its
   dedicated subnet must have no delegation and must have the deployed NSG.
4. Confirm the API Management managed identity has `Cognitive Services OpenAI
   User` on the Foundry account.
5. Run the shared Chat Completions app with `--scenario 00c` against the default
   direct target from an external machine. The private Foundry endpoint is
   expected to return 403, "Public access is disabled", before any inference.
6. Apply the gateway policy after that negative test:

   ```bash
   scripts/apply-00c-apim-policy.sh <azd-environment-name>
   ```

7. Run the same shared app with `--scenario 00c --target gateway`. APIM validates
   the caller token and allowlist, acquires its own backend token, and sends the
   request through the VNet to Foundry. See the [app README](../app/README.md#run)
   for the commands and the
   [repository README](../../../README.md#published-episodes) for the companion
   LinkedIn articles.

Static validation is available through [the lane tests](test/README.md).

Live validation on 2026-10-01 (azd environment `scenario`, `italynorth`):
provisioning succeeded in 32 minutes, mostly API Management activation; all 24
live checks passed. From an external machine, the direct call returned 403
"Public access is disabled. Please configure private endpoint." After the
policy, the gateway returned 401 without a token or with a malformed token, and
200 with the expected model answer and the `x-foundrylab-gateway` header for the
allowlisted caller. The direct call still returned 403 afterwards. The 403 path
for a valid but non-allowlisted token was not exercised.

## Per-caller token limit (opt-in)

The [Token Governance guide](../app/token_limit_demo-explained.md) explains
`llm-token-limit`, keyed by the validated Entra object ID after authorization.
`AZURE_APIM_TOKENS_PER_MINUTE` defaults to `0`, including in bootstrap.
Successful responses expose consumed/remaining token headers; a caller over
budget receives 429 and Retry-After. This is a gateway budget, not model
capacity, content filtering, a cost ledger or a strict maximum per response:
a request started below the budget can finish above it.

From this lane directory:

```bash
environment=<your-00c-azd-environment>
azd env set AZURE_APIM_TOKENS_PER_MINUTE 600 --environment "$environment"
```

Then, from the repository root, apply the policy and optionally create B:

```bash
scripts/manage-second-caller.sh 00c create "$environment"
scripts/apply-gateway-policy.sh 00c "$environment"
cd scenarios/00-foundry-core/app
python token_limit_demo.py --environment "$environment" --scenario 00c \
  --caller-b-config-dir ../../../.azure/00c-second-caller/<your-00c-azd-environment>/az
```

The service principal has no Azure role, a one-day certificate and a separate
ignored Azure CLI profile. App registration permission is required; an
already-authorized second user is a manual alternative. The existing
`apply-00c-apim-policy.sh` and `manage-00c-second-caller.sh` names remain thin
wrappers for backward compatibility.

The 2026-11-02 Italy North run observed nine 200 responses (639 tokens against
a 600 budget), then 429 with Retry-After 41 seconds, B 200, and A 200 after
42 seconds. Developer uses a sliding window; Basic v2 on 00a uses token bucket.
The lab and second caller were removed. Model-side 429, streaming and multiple
gateway instances were not exercised.

From the root, cleanup B and reapply the allowlist:

```bash
scripts/manage-second-caller.sh 00c cleanup "$environment"
scripts/apply-gateway-policy.sh 00c "$environment"
```

Set the budget to `0` and reapply the policy to disable the limit.

## Per-caller usage metrics (opt-in)

The shared policy also supports `AZURE_APIM_USAGE_METRICS=true`, default false.
Applying it creates [telemetry resources](../../../modules/apim/foundry-usage-metrics/main.bicep)
with Entra-only ingestion and no request/response body logging, and emits
`llm-emit-token-metric` with Caller from the validated object ID.
The [usage report](../app/usage_report-explained.md) compares that metric with
model counters and demo response headers. This support is included for the
00c Usage Attribution companion and the 00a Public Gateway bypass
demonstration. The Usage Attribution article is **Not yet published** on LinkedIn.

From this lane directory:

```bash
environment=<your-00c-azd-environment>
azd env set AZURE_APIM_USAGE_METRICS true --environment "$environment"
```

Then, from the repository root:

```bash
bash scripts/apply-gateway-policy.sh 00c "$environment"
```

This creates monitoring resources and records the workspace outputs in azd.
The Python report itself only queries data; its signed-in user needs workspace
query and Foundry account metric read permissions. No token limit or second
caller is required just to collect metrics; those are separate prerequisites
for comparing the bounded token demo's A/B response headers.

Disabling metrics does not delete previous monitoring resources.

## Cleanup

From this lane directory, after confirming the selected environment:

```bash
azd down --force --purge
```

Remove any separately created client connectivity and verify that the lab
resources have been removed. No other lane needs to remain deployed.

## References

- [Microsoft Foundry private networking](https://learn.microsoft.com/azure/foundry/how-to/configure-private-link)
- [Level overview](../README.md)