# A Learning Guide to main.bicep: Public Foundry Core, Scenario 00a

This guide explains how to read [main.bicep](main.bicep), how its resources
are built, and which operations the template actually performs.
It covers the scenario 00a template: Microsoft Foundry with public access,
Microsoft Entra ID authentication, and the `gpt-4.1-mini` model.

## 1. The Big Picture

Bicep is a declarative language for describing Azure infrastructure.
It does not contain a sequence of commands to execute from top to bottom:
it describes the desired state and the dependencies between resources.

Bicep is compiled into an Azure Resource Manager (ARM) template. Azure
Resource Manager uses that template to create or update resources.

This `main.bicep` primarily serves as a coordinator:

1. Receives the scenario parameters.
2. Computes deterministic names.
3. Calls a shared module that creates the account, project, and model deployment.
4. Adds two role assignments for the user working with the scenario.
5. Exposes the identifiers needed by subsequent steps.

The resulting hierarchy looks like this:

```text
Existing resource group
|
+-- Microsoft Foundry account
    |   kind: AIServices
    |   Account SKU: S0
    |
    +-- Foundry project
    |   +-- Foundry User assigned to the user at project scope
    |
    +-- gpt-4.1-mini deployment
    |   Model: gpt-4.1-mini, version 2025-04-14
    |   Deployment SKU: GlobalStandard, capacity: 30
    |
    +-- Cognitive Services OpenAI User assigned to the user at account scope
```

**The project and the model deployment are both children of the account.**
The deployment is not a child resource of the project, even though the project
lets you work with models available in the account.

## 2. The Files Involved

| File | Responsibility |
| --- | --- |
| [main.bicep](main.bicep) | Coordinates the scenario and declares the user's RBAC assignments. |
| [main.bicepparam](main.bicepparam) | Supplies parameter values by reading environment variables. |
| [azure.yaml](../azure.yaml) | Tells Azure Developer CLI which resource group and template to use. |
| [Shared Foundry module](../../../../modules/core/foundry-project/main.bicep) | Creates the account, project, managed identities, and model deployment. |

To understand everything that gets created, counting the `resource` blocks
in the main file is not enough: you also need to read the referenced module.

## 3. Scope: Where Deployment Takes Place

```bicep
targetScope = 'resourceGroup'
```

The template operates within a resource group selected by the caller.
It does not create the resource group or independently choose the subscription.

In the scenario workflow, bootstrap prepares the environment and resource
group; `azd` then uses the configuration in [azure.yaml](../azure.yaml) to
target provisioning. The `subscription()` and `resourceGroup()` functions
read this deployment context.

## 4. Parameters: The Template's Inputs

A `param` makes a value configurable. If no default value is provided,
the caller must supply it.

| Parameter | Type | Template default | Meaning |
| --- | --- | --- | --- |
| `location` | `string` | None | Region for the account and project. |
| `environmentName` | `string` | None | Environment name, used to construct resource names. |
| `modelName` | `string` | `gpt-4.1-mini` | Model name and, in the current module, its deployment name as well. |
| `modelFormat` | `string` | `OpenAI` | Model format/provider. |
| `modelVersion` | `string` | `2025-04-14` | Specific model version. |
| `modelSkuName` | `string` | `GlobalStandard` | Deployment type for inference. |
| `modelCapacity` | `int` | `30` | Deployment capacity; for this configuration, 30 thousand tokens per minute. |
| `deployerPrincipalId` | `string` | None | Entra object ID of the user who will receive the roles. |

### Descriptions and Constraints

`@description(...)` documents the parameter. It does not perform an Azure operation.

The `deployerPrincipalId` parameter also has:

```bicep
@minLength(36)
@maxLength(36)
```

These constraints require a 36-character string. They **do not verify**
that the string is a valid UUID, that the user exists, or that it identifies
the currently authenticated user.

The value must be the user's object ID, not the subscription ID, tenant ID,
or application ID. The scenario bootstrap retrieves it from the Azure CLI user.

### Template Defaults and Environment Values

[main.bicepparam](main.bicepparam) reads the following environment variables:

| Environment variable | Parameter | Fallback in the parameter file |
| --- | --- | --- |
| `AZURE_LOCATION` | `location` | `italynorth` |
| `AZURE_ENV_NAME` | `environmentName` | `dev` |
| `AZURE_DEFAULT_MODEL` | `modelName` | `gpt-4.1-mini` |
| `AZURE_DEFAULT_MODEL_VERSION` | `modelVersion` | `2025-04-14` |
| `AZURE_DEFAULT_MODEL_SKU` | `modelSkuName` | `GlobalStandard` |
| `AZURE_DEFAULT_MODEL_CAPACITY` | `modelCapacity` | `30`, converted to an integer |
| `AZURE_DEPLOYER_PRINCIPAL_ID` | `deployerPrincipalId` | All-zero UUID, to be replaced through bootstrap |

Therefore, `italynorth` is not a default in `main.bicep`: it is the fallback
in the parameter file. By contrast, `modelFormat` is not passed by the
parameter file and retains the template's `OpenAI` default.

Capacity is not a measurement of observed response speed.
Deployment requires model/version/SKU availability and sufficient quota.
Also, `GlobalStandard` does not guarantee that inference processing remains
in the account's region.

## 5. Variables: How Names Are Constructed

`var` declarations compute values from the inputs and context.
They do not create resources.

### Normalizing the Environment Name

```bicep
var normalizedEnvironmentName = toLower(replace(environmentName, '_', '-'))
```

This converts the name to lowercase and replaces `_` with `-`.
For example, `Demo_Lab` becomes `demo-lab`.

```bicep
var namePrefix = length(take(normalizedEnvironmentName, 20)) >= 3
  ? take(normalizedEnvironmentName, 20)
  : 'dev'
```

The ternary operator `condition ? valueIfTrue : valueIfFalse` selects:

- The first 20 characters, if the result contains at least three characters.
- `dev`, if the name is too short.

This is not comprehensive sanitization: characters other than those
explicitly handled are not removed.

### Deterministic Suffix and Final Names

```bicep
var compactNamePrefix = toLower(replace(replace(namePrefix, '-', ''), '_', ''))
var resourceToken = uniqueString(subscription().id, resourceGroup().id, namePrefix)
var accountName = take('ai${compactNamePrefix}${resourceToken}', 64)
var projectName = 'core-${resourceToken}'
```

| Step | Example using `Demo_Lab` |
| --- | --- |
| Normalized name and prefix | `demo-lab` |
| Compact prefix for the account | `demolab` |
| Deterministic token | `<token>` |
| Account name | `aidemolab<token>` |
| Project name | `core-<token>` |

`uniqueString(...)` returns a deterministic 13-character suffix:
with the same subscription, resource group, and prefix, the result stays
the same. It reduces the risk of collisions, but it is not a global name
reservation, a password, or a new random value for each deployment.

`take(..., 64)` limits the account name's length.

**Why do these calculations also appear in the module?** The module uses
the names to create resources; the main template reconstructs them to
reference the same resources in its `existing` blocks. The two naming
implementations must remain aligned.

## 6. The Module: Where the Main Resources Are Created

```bicep
module foundryProject '../../../../modules/core/foundry-project/main.bicep' = {
  params: {
    // Parameters passed to the module.
  }
}
```

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
The resources' managed identities are not the user identified by
`deployerPrincipalId`: they are separate identities.

## 7. The existing Blocks: References, Not New Resources

```bicep
resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: accountName
}
```

`existing` tells Bicep to reference a resource without creating or updating
it through that block.

The project reference also specifies its parent:

```bicep
resource foundryProjectResource 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' existing = {
  parent: foundryAccount
  name: projectName
}
```

In this case, the module creates the resources during the same provisioning
operation. The `existing` references let the main file obtain their resource
IDs and use them as RBAC scopes.

There is no duplication: the module creates resources, while the `existing`
blocks reference them. Nor does this mean that the account and project must
have been deployed manually beforehand.

The part after `@` is the Azure resource API version. It should not be confused
with `modelVersion`, which identifies the language model version.

## 8. RBAC: Who Can Do What

The two `Microsoft.Authorization/roleAssignments` blocks assign built-in
roles to the user identified by `deployerPrincipalId`.

| Symbolic name | Role | Scope |
| --- | --- | --- |
| `deployerOpenAiUser` | Cognitive Services OpenAI User | Foundry account |
| `deployerFoundryUser` | Foundry User | Foundry project |

The first role enables the use of Azure OpenAI inference APIs within
the account. The second grants the project privileges required by the
benchmark's Microsoft Foundry Evaluation run.

**Pay attention to scope:** a role's name does not automatically extend
an assignment beyond the resource to which it applies. A Foundry User
assignment on a project is not equivalent to an Owner assignment on the
subscription. Because the model deployment is a child of the account,
the ARM operations that create it require authorization at that level too.
The project-scoped role alone should not be considered sufficient evidence
of all the permissions required to deploy models.

### The Properties of a Role Assignment

```bicep
properties: {
  principalId: deployerPrincipalId
  principalType: 'User'
  roleDefinitionId: subscriptionResourceId(
    'Microsoft.Authorization/roleDefinitions',
    '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  )
}
```

- `principalId`: identifies the recipient of the role.
- `principalType: 'User'`: indicates an Entra user, not a managed identity.
- `roleDefinitionId`: identifies the built-in role definition.
- `subscriptionResourceId(...)`: constructs the role definition's
  resource ID; it **does not set the assignment's scope**.

The IDs used are:

| Role | Definition ID |
| --- | --- |
| Cognitive Services OpenAI User | `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd` |
| Foundry User | `53ca6127-db72-4b80-b1b0-d745d6d5456d` |

The actual scope is declared separately, for example through
`scope: foundryAccount`.

### Why Use guid(...) for the Name?

```bicep
name: guid(foundryAccount.id, deployerPrincipalId, 'Cognitive Services OpenAI User')
```

RBAC assignments require a GUID-formatted name. `guid(...)` generates it
deterministically from the combination of resource, user, and role.
Repeating provisioning with the same values targets the same assignment,
instead of creating one with a random name.

The caller performing provisioning must already be able to create resources
and assign roles. The template cannot grant itself permissions that the
caller does not possess. After an assignment, RBAC propagation may take
time before an application call succeeds.

## 9. Dependencies: The Actual Order

The module declares `parent: account` for both the project and the model
deployment. This establishes an implicit dependency on the account.

The model deployment also contains `dependsOn: [project]`.
The scenario therefore waits for project creation before creating the
deployment, avoiding concurrent operations on the same account.

In the main template, both RBAC assignments contain:

```bicep
dependsOn: [
  foundryProject
]
```

Here, `foundryProject` means **the entire module**. The assignments wait
for the module to finish, including its resources.
The `existing` reference alone would not express this dependency on the module.

```text
Parameters and name calculation
            |
            v
foundryProject module
  Account --> Project --> Model deployment
            |
            v
Module completion
            |
            +--> OpenAI User role on the account
            |
            +--> Foundry User role on the project
```

The two RBAC assignments do not depend on each other and can be handled
in parallel after the module. The order of blocks in the file does not
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
| `AZURE_AI_PROJECT_PRINCIPAL_ID` | Principal ID of the project's managed identity | Any permissions granted to the project for accessing other services. |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Model deployment name | Deployment selection in inference requests. |

For example:

```bicep
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = foundryProject.outputs.modelDeploymentName
```

The output contains the deployment name, not model weights, a generated
response, or an API key. In the `azd` workflow, these outputs populate the
environment used by the scenario's clients.

The project's principal ID is not `deployerPrincipalId`: the former
belongs to the project's managed identity, while the latter belongs to
the user.

## 11. What Happens If I Repeat Provisioning?

With the same parameters and context:

- The computed names remain stable.
- Azure Resource Manager creates or updates the resources targeted by the template.
- The RBAC assignment GUIDs remain stable.

This makes deployment repeatable, but it does not mean every change is
without consequences:

- Changing `environmentName` may change resource names.
- Changing `modelName` changes both the selected model and the deployment
  name in the current module.
- Changing `modelVersion` or capacity requires Azure to support the
  update and sufficient quota to be available.
- Changing the user or role produces a different assignment GUID.

A normal incremental ARM deployment does not automatically delete an old
resource or assignment simply because it no longer appears in the template.
Removals require explicit handling.

## 12. What This Template Does Not Do

`main.bicep` prepares the infrastructure and roles, but it does not:

- Create the resource group.
- Execute Chat Completions requests.
- Upload datasets or start a fine-tuning job.
- Create the custom deployment resulting from an SFT job.
- Run benchmarks or Foundry Evaluation.
- Create agents, hosted applications, Search, Storage, or Cosmos DB.
- Configure VNets, private endpoints, API Management, or application monitoring.

In particular, having a base model that supports fine-tuning does not
mean that it has already been fine-tuned. Evaluation operations belong to the
[application pipeline](../../app/README.md), not this template.

## 13. A Practical Reading Order

A useful order for studying the file is:

1. Read `targetScope` to understand the context.
2. Read the `param` declarations to distinguish required inputs, defaults, and configurable values.
3. Follow the `var` declarations to understand how names are derived.
4. Open the module to see the resources actually created.
5. Distinguish `existing` references from resources to be deployed.
6. Read RBAC as a combination of **identity, role, and scope**.
7. Follow `parent` and `dependsOn` to reconstruct the actual order.
8. Read the `output` declarations to understand how the application locates the resources.

In short: **the main template configures and coordinates; the module
builds the Foundry foundation; RBAC authorizes the user; and outputs connect
provisioning to the application.**

For prerequisites and the complete operational procedure, see the
[scenario 00a README](../README.md).
