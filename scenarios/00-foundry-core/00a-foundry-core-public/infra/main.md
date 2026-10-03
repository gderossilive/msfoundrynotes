# A Learning Guide to main.bicep: Public Foundry Core, Scenario 00a

This guide explains how to read [main.bicep](main.bicep), how its resources
are built, and which operations the template actually performs.
It covers the scenario 00a template published in Microsoft Foundry Notes:
Microsoft Foundry (new) with public access, Microsoft Entra ID authentication,
and the default `gpt-5-mini` model.

The guide follows this repository's template, not the evolved version in
FoundryScenarios: this version has no `deployerPrincipalId` parameter,
`existing` resource references, or user role assignments.

## 1. The Big Picture

Bicep is a declarative language for describing Azure infrastructure.
It does not contain a sequence of commands to execute from top to bottom:
it describes the desired state and the dependencies between resources.

Bicep is compiled into an Azure Resource Manager (ARM) template. Azure
Resource Manager uses that template to create or update resources.

This `main.bicep` primarily serves as a coordinator:

1. Receives the scenario parameters.
2. Normalizes the environment name into a resource-name prefix.
3. Calls a shared module that creates the account, project, and model deployment.
4. Exposes identifiers needed by clients and subsequent operations.

The resulting hierarchy looks like this:

```text
Existing resource group
|
+-- Microsoft Foundry account
    |   kind: AIServices
    |   Account SKU: S0
    |   System-assigned managed identity
    |
    +-- Foundry project
    |   System-assigned managed identity
    |
    +-- gpt-5-mini deployment
        Model: gpt-5-mini, version 2025-08-07
        Deployment SKU: GlobalStandard, capacity: 30
```

**The project and the model deployment are both children of the account.**
The deployment is not a child resource of the project, even though the project
lets you work with models available in the account.

The template creates no role assignments for the deploying user.

## 2. The Files Involved

| File | Responsibility |
| --- | --- |
| [main.bicep](main.bicep) | Coordinates the scenario and forwards module outputs. |
| [main.bicepparam](main.bicepparam) | Supplies parameter values by reading environment variables. |
| [azure.yaml](../azure.yaml) | Tells Azure Developer CLI which resource group and template to use. |
| [Shared Foundry module](../../../../modules/core/foundry-project/main.bicep) | Computes resource names and creates the account, project, managed identities, and model deployment. |

To understand everything that gets created, counting the `resource` blocks
in the main file is not enough: this entry point has none. You need to read
the referenced module.

## 3. Scope: Where Deployment Takes Place

```bicep
targetScope = 'resourceGroup'
```

The template operates within a resource group selected by the caller.
It does not create the resource group or independently choose the subscription.

In the scenario workflow, bootstrap prepares the environment and resource
group; `azd` then uses the configuration in [azure.yaml](../azure.yaml) to
target provisioning. The shared module's `subscription()` and `resourceGroup()`
functions read this deployment context.

## 4. Parameters: The Template's Inputs

A `param` makes a value configurable. If no default value is provided,
the caller must supply it. `@description(...)` documents the parameter;
it does not perform an Azure operation.

| Parameter | Type | Template default | Meaning |
| --- | --- | --- | --- |
| `location` | `string` | None | Region for the account and project. |
| `environmentName` | `string` | None | Environment name, used to construct resource names. |
| `modelName` | `string` | `gpt-5-mini` | Model name and, in the current module, its deployment name as well. |
| `modelFormat` | `string` | `OpenAI` | Model format/provider. |
| `modelVersion` | `string` | `2025-08-07` | Specific model version. |
| `modelSkuName` | `string` | `GlobalStandard` | Deployment type for inference. |
| `modelCapacity` | `int` | `30` | Deployment capacity; for this configuration, 30 thousand tokens per minute. |

### Template Defaults and Environment Values

[main.bicepparam](main.bicepparam) reads the following environment variables:

| Environment variable | Parameter | Fallback in the parameter file |
| --- | --- | --- |
| `AZURE_LOCATION` | `location` | `italynorth` |
| `AZURE_ENV_NAME` | `environmentName` | `dev` |
| `AZURE_DEFAULT_MODEL` | `modelName` | `gpt-5-mini` |
| `AZURE_DEFAULT_MODEL_VERSION` | `modelVersion` | `2025-08-07` |
| `AZURE_DEFAULT_MODEL_SKU` | `modelSkuName` | `GlobalStandard` |
| `AZURE_DEFAULT_MODEL_CAPACITY` | `modelCapacity` | `30`, converted to an integer |

Therefore, `italynorth` is not a default in `main.bicep`: it is the fallback
in the parameter file. By contrast, `modelFormat` is not passed by the
parameter file and retains the template's `OpenAI` default.

The shared module has its own model defaults, but this scenario overrides
them with the values passed by the entry point. Change model name and version
together when choosing another supported model.

Capacity is not a measurement of observed response speed.
Deployment requires model/version/SKU availability and sufficient quota.
Also, `GlobalStandard` does not guarantee that inference processing remains
in the account's region.

## 5. Variables: How Names Are Constructed

`var` declarations compute values from the inputs and context.
They do not create resources.

### Normalizing the Environment Name in the Entry Point

```bicep
var normalizedEnvironmentName = toLower(replace(environmentName, '_', '-'))
var namePrefix = length(take(normalizedEnvironmentName, 20)) >= 3
  ? take(normalizedEnvironmentName, 20)
  : 'dev'
```

The first expression converts the name to lowercase and replaces `_` with `-`.
For example, `Demo_Lab` becomes `demo-lab`.

The ternary operator `condition ? valueIfTrue : valueIfFalse` selects:

- The first 20 characters, if the result contains at least three characters.
- `dev`, if the name is too short.

This is not comprehensive sanitization: characters other than those
explicitly handled are not removed.

### Deterministic Suffix and Final Names in the Shared Module

The entry point passes `namePrefix` to the module, which computes:

```bicep
var compactNamePrefix = toLower(replace(replace(namePrefix, '-', ''), '_', ''))
var resourceToken = uniqueString(subscription().id, resourceGroup().id, namePrefix)
var accountName = take('ai${compactNamePrefix}${resourceToken}', 64)
var resolvedProjectName = take('${projectName}-${resourceToken}', 64)
```

| Step | Example using `Demo_Lab` |
| --- | --- |
| Normalized name and prefix | `demo-lab` |
| Compact prefix for the account | `demolab` |
| Deterministic token | `<token>` |
| Account name | `aidemolab<token>` |
| Project name, using the scenario's `core` prefix | `core-<token>` |

`uniqueString(...)` returns a deterministic 13-character suffix:
with the same subscription, resource group, and prefix, the result stays
the same. It reduces the risk of collisions, but it is not a global name
reservation, a password, or a new random value for each deployment.

`take(..., 64)` limits each resource name's length. The main template does
not reconstruct these names; it obtains them through module outputs.

## 6. The Module: Where the Main Resources Are Created

The entry point declares a module named `foundryProject`, referencing
`../../../../modules/core/foundry-project/main.bicep`.

`foundryProject` is a Bicep symbolic name for the module, not the project's
Azure resource name. The relative path identifies the shared file.
The module is deployed into the same resource group because no different
scope is specified.

The template passes the region, prefix, and model configuration to the module,
along with several scenario-specific choices:

| Value passed | Effect |
| --- | --- |
| `disableLocalAuth: true` | Disables local key-based authentication for the account. |
| `projectName: 'core'` | Supplies the project name prefix, to which the module appends the token. |
| `projectDescription` | Sets a human-readable project description. |
| `projectDisplayName: 'FoundryLab core'` | Sets the display name, which is separate from the resource name. |

Inside the [shared module](../../../../modules/core/foundry-project/main.bicep):

1. **The account** has type `Microsoft.CognitiveServices/accounts`,
   `kind: 'AIServices'`, and SKU `S0`; it enables project management.
2. **The project** has type `Microsoft.CognitiveServices/accounts/projects`
   and is linked to the account through `parent`.
3. **The model deployment** has type
   `Microsoft.CognitiveServices/accounts/deployments`, also uses
   `parent: account`, and receives its name, version, format, SKU, and capacity.

The account's `S0` SKU and the deployment's `GlobalStandard` SKU are two
different settings: the first applies to the Foundry resource, while the
second applies to the model's inference service.

### Module Defaults That Matter for Scenario 00a

The main template does not pass every module parameter. Omitted parameters
use these defaults:

- `publicNetworkAccess: 'Enabled'`: a public endpoint and network rules
  with a default action of `Allow`.
- No user-assigned identity specified: the account and project each
  receive a system-assigned managed identity.
- `enableManagedNetwork: false`: no managed network injection for agents.

**Public does not mean anonymous.** Network reachability is public,
but calls require authentication and authorization.

## 7. Resource Declarations and References

The shared module declares resources to create or update. For example:

```bicep
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: account
  name: resolvedProjectName
  location: location
  identity: foundryIdentity
  properties: {
    description: projectDescription
    displayName: projectDisplayName
  }
}
```

`project` is a symbolic name used by Bicep expressions. The Azure resource
name is the value of `resolvedProjectName`; `parent: account` places it
under the account.

The part after `@` is the Azure resource API version. It should not be confused
with `modelVersion`, which identifies the language model version.

Neither the entry point nor this shared module uses `existing` blocks.
In Bicep, `existing` would reference a resource without creating or updating
it through that block. Here, resources are created by the module and their
identifiers are exposed through outputs instead.

## 8. Authentication and RBAC: What Must Be Done Separately

The account and project each receive a system-assigned managed identity.
These identities let the resources authenticate to other services, but
creating an identity grants it no permissions on its own.

The person or application calling the model uses its **own** Entra identity.
The resources' managed identities are not the deploying user's identity.

This template does not declare any `Microsoft.Authorization/roleAssignments`
resources. In particular:

- It does not grant the deploying user inference permission.
- It does not assign Foundry Owner at project scope.
- It does not make provisioning success proof that inference will succeed.

The caller needs an appropriate role, such as **Cognitive Services OpenAI
User**, at the Foundry account scope. Follow
[Testing and inference](../../../../docs/testing.md) for the authorization
procedure and a manual keyless request.

Read RBAC as a combination of **identity, role, and scope**:

- **Identity:** who is receiving access.
- **Role:** which operations are permitted.
- **Scope:** where those permissions apply.

A project-scoped role does not automatically authorize operations on a model
deployment, which is a sibling under the account. Resource creation and role
assignment also require appropriate permissions held by the provisioning caller.
After a role assignment, propagation may take time before a request succeeds.

## 9. Dependencies: The Actual Order

The module declares `parent: account` for both the project and the model
deployment. This establishes an implicit dependency on the account.

The model deployment also contains:

```bicep
dependsOn: [
  project
]
```

The scenario therefore waits for project creation before creating the
deployment, avoiding concurrent operations on the same account.

```text
Parameters and prefix calculation
            |
            v
foundryProject module
  Account --> Project --> Model deployment
            |
            v
Module outputs --> Scenario outputs
```

The model deployment appears before the project in the module's source file.
That does not change the deployment order: dependencies, not line position,
define the execution order.

## 10. Outputs: The External Contract

`output` declarations expose deployment values retrieved from the module's
outputs:

| Output | Contents | Purpose |
| --- | --- | --- |
| `AZURE_AI_ACCOUNT_ID` | Full account resource ID | Resource management and scope definition. |
| `AZURE_AI_ACCOUNT_NAME` | Account name | Resource lookup and endpoint construction by clients. |
| `AZURE_AI_PROJECT_ID` | Full project resource ID | Management operations and RBAC on the project. |
| `AZURE_AI_PROJECT_NAME` | Project name | Project identification in Foundry clients. |
| `AZURE_AI_PROJECT_PRINCIPAL_ID` | Principal ID of the project's managed identity | Any permissions granted separately to the project for accessing other services. |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Model deployment name | Deployment selection in inference requests. |

For example:

```bicep
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = foundryProject.outputs.modelDeploymentName
```

The output contains the deployment name, not model weights, a generated
response, or an API key. In the `azd` workflow, these outputs populate the
environment used by subsequent client commands.

The project's principal ID belongs to its managed identity, not to the
deploying user. Returning that ID does not grant the identity a role.

## 11. What Happens If I Repeat Provisioning?

With the same parameters and context:

- The computed names remain stable.
- Azure Resource Manager creates or updates the resources targeted by the template.
- No user role assignments are created, on either the first or later runs.

This makes deployment repeatable, but it does not mean every change is
without consequences:

- Changing `environmentName` may change resource names.
- Changing `modelName` changes both the selected model and the deployment
  name in the current module.
- Changing `modelVersion` or capacity requires Azure to support the
  update and sufficient quota to be available.

A normal incremental ARM deployment does not automatically delete an old
resource simply because it no longer appears in the template.
Removals require explicit handling.

## 12. What This Template Does Not Do

`main.bicep` prepares the infrastructure, but it does not:

- Create the resource group.
- Assign roles to the deploying user or an application.
- Execute Chat Completions requests.
- Upload datasets or start a fine-tuning job.
- Create a custom deployment resulting from a fine-tuning job.
- Run benchmarks or Foundry Evaluation.
- Create agents, hosted applications, Search, Storage, or Cosmos DB.
- Configure VNets, private endpoints, API Management, or application monitoring.

Deploying a base model does not mean it has been fine-tuned or that its selected
version supports fine-tuning. Check model support before planning a separate
customization workflow. This repository's scenario has
[no application component](../../app/README.md) or fine-tuning pipeline.

## 13. A Practical Reading Order

A useful order for studying the file is:

1. Read `targetScope` to understand the context.
2. Read the `param` declarations to distinguish required inputs, defaults, and configurable values.
3. Follow the entry point's `var` declarations to understand prefix normalization.
4. Open the module to see final name calculation and the resources actually created.
5. Distinguish symbolic names, Azure resource names, and resource IDs.
6. Separate resource identities from the caller's identity and permissions.
7. Follow `parent` and `dependsOn` to reconstruct the actual order.
8. Read the `output` declarations to understand how clients locate the resources.

In short: **the main template configures and coordinates; the module
builds the Foundry foundation; outputs expose its identifiers; and caller
authorization is a separate step.**

For prerequisites and the complete operational procedure, see the
[scenario 00a README](../README.md).
