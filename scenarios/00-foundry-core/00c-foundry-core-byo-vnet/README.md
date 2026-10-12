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

The initial deployment creates the API, backend, managed identity, and backend
role assignment, but deliberately does not attach its forwarding policy. Apply
the policy only after observing the expected failure of a direct external call
to Foundry. This makes the boundary visible without exposing Foundry itself.

No agent, capability host, agent subnet delegation, managed outbound network,
search, storage, telemetry, VM, VPN, or Bastion is provisioned. In particular,
private inbound access and the APIM gateway do not demonstrate agent outbound
isolation.

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
   request through the VNet to Foundry. See the app README and the LinkedIn
   companion article for the full command sequence.

Static validation is available through [the lane tests](test/README.md).

Live validation on 2026-10-01 (azd environment `scenario`, `italynorth`):
provisioning succeeded in 32 minutes, mostly API Management activation; all 24
live checks passed. From an external machine, the direct call returned 403
"Public access is disabled. Please configure private endpoint." After the
policy, the gateway returned 401 without a token or with a malformed token, and
200 with the expected model answer and the `x-foundrylab-gateway` header for the
allowlisted caller. The direct call still returned 403 afterwards. The 403 path
for a valid but non-allowlisted token was not exercised.

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