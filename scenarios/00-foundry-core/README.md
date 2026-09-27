# Level 00: Foundry Core

This level establishes a Microsoft Foundry account, project, and model deployment.
This publication includes only the independently deployable 00a public lane.
It creates no agent and requires no other lane's deployment.

| Lane | Status | Focus |
| --- | --- | --- |
| [00a Foundry Core public](00a-foundry-core-public/README.md) | Implemented; static checks passed | Public Foundry foundation |

## Network and identity boundaries

Lane 00a enables public access without client IP restrictions. It creates no
VNet, private endpoint or managed agent network.

Key-based authentication is disabled. The account and project use system-assigned
managed identities. Callers still need their own Entra ID permissions for
inference; the template does not assign those permissions to the deployer.

## Validation status

The public package was checked locally:

- The 00a Core lane suite passed all 4 static checks.
- The 00a Bicep parameter file compiled without diagnostics.
- All 33 bootstrap checks and 7 scenario-metadata checks passed.

No Azure deployment or live inference was performed as part of this update.
Static compilation does not prove Azure deployment or inference. Follow the
00a README for prerequisites, costs, validation and cleanup.

## Next steps

1. Review regional availability, quota, permissions, policy requirements and costs.
2. Authorize and run the public lane's deployment in its own environment.
3. Run its live checks and test inference with an authorized client.
4. Verify cleanup before marking the environment as removed.

Use the [public repository guide](../../README.md) for setup and the
[testing guide](../../docs/testing.md) for live checks and manual keyless inference.
Level 00 has no scenario-local `blog/` directory. Editorial drafts are not included
in this source publication.