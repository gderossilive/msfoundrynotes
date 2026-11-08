# Level 00: Foundry Core

This level establishes a Microsoft Foundry account, project, and model
deployment. It creates no agent and requires no other lane's deployment.

| Lane | Status | Focus |
| --- | --- | --- |
| [00a Foundry Core public](00a-foundry-core-public/README.md) | Implemented; static and historical live checks passed | Public endpoint, clients, benchmark, fine-tuning, optional model monitoring and Basic v2 gateway |
| [00c Foundry Core BYO VNet](00c-foundry-core-byo-vnet/README.md) | Implemented; static and historical live checks passed | Private endpoint, customer-managed VNet, API Management Developer and optional per-caller token budget |

## Network and identity boundaries

Lane 00a enables public network access, disables key authentication, and grants
the signed-in human deployer **Cognitive Services OpenAI User** on the account for
inference and **Foundry Owner** on the project, which Foundry Evaluation and
fine-tuned checkpoint deployment require.

Lane 00c disables public network access and creates a private endpoint, three
private DNS zones, and API Management Developer in an external VNet subnet.
The gateway validates the caller and uses its own managed identity to reach the
model. The initial deployment deliberately omits the API policy so the direct
failure can be observed before the gateway path is enabled.

The [optional 00a gateway](app/public_gateway-explained.md) does not close its
direct Foundry path. The [token policy](app/token_limit_demo-explained.md) is
shared with 00c; only traffic through APIM is budgeted and attributed.
The [monitoring companion](app/monitor_model-explained.md) has no agent.

Neither lane implements agent outbound isolation, tools, retrieval, application
hosting, business-data access, VPN, ExpressRoute, or production readiness.

## Validation status

- Both Bicep parameter files compile without diagnostics.
- Lane 00a static checks validate its caller roles and application contract.
- Lane 00c static checks validate private networking, the APIM deployment, and
  the separately applied gateway policy.
- All Python client, monitoring, token demo and report tests use mocks and do not call Azure.
- Live validation was observed on 2026-10-01 and 2026-10-02; reproduce the
  checks in your own subscription.
- Monitoring was observed on 2026-11-01 in Sweden Central, and per-caller
  budgets/public gateway on 2026-11-02 in Italy North. The guides distinguish
  those historical results from configured or unverified signals.

The [repository README](../../README.md#published-episodes) maps each published
episode to its lane and covers setup. Use the
[testing guide](../../docs/testing.md) for validation and the
[application guide](app/README.md) for the client commands.
