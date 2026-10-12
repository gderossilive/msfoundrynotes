# Lane 00c checks

From the repository root:

```bash
bash scenarios/00-foundry-core/00c-foundry-core-byo-vnet/test/test-scenario.sh --static
```

Static checks compile the initial deployment and the separately applied APIM
policy. They check that Foundry remains private, APIM Developer is injected into
an external VNet subnet with the required NSG, no policy is installed during
initial deployment, and the later policy validates Entra ID callers before
using the gateway managed identity. They do not prove deployment, private DNS
resolution, or inference.

After an explicitly authorized deployment, use `TEST_AZD_ENV=<lane-environment>`
with `--live` to inspect the resources. The live check verifies the deployed Foundry private endpoint, APIM Developer
configuration, API, subnet/NSG, and gateway backend role. It does not require
the policy to have been applied. For the ordered direct-failure and
gateway-success inference demonstration, follow the lane and shared app README.
No jumpbox, VPN, or Bastion is created by this lane.