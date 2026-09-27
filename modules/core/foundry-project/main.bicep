targetScope = 'resourceGroup'

@description('Azure region for the Foundry account and project.')
param location string

@minLength(3)
@description('Prefix used to produce deterministic resource names.')
param namePrefix string

@description('Resource ID of a user-assigned managed identity. When empty, the account and project use system-assigned identities.')
param userAssignedIdentityResourceId string = ''

@description('Principal ID of the user-assigned managed identity. Required when userAssignedIdentityResourceId is set.')
param userAssignedIdentityPrincipalId string = ''

@description('Name for the Foundry project.')
param projectName string = 'project'

@description('Description for the Foundry project.')
param projectDescription string = 'A Microsoft Foundry project deployed by FoundryLab.'

@description('Display name for the Foundry project.')
param projectDisplayName string = 'FoundryLab project'

@description('Model deployment name.')
param modelName string = 'gpt-4.1'

@description('Model provider format.')
param modelFormat string = 'OpenAI'

@description('Model version.')
param modelVersion string = '2025-04-14'

@description('Model deployment SKU name.')
param modelSkuName string = 'GlobalStandard'

@description('Model deployment capacity in thousands of tokens per minute.')
param modelCapacity int = 30

@description('Whether local key-based authentication is disabled for the Foundry account.')
param disableLocalAuth bool = false

@allowed([
  'Enabled'
  'Disabled'
])
@description('Public network access for the Foundry account. Disabled requires a private endpoint for data-plane access.')
param publicNetworkAccess string = 'Enabled'

@description('Configure Microsoft-managed agent network injection at account creation. Does not create an agent or managed network resource.')
param enableManagedNetwork bool = false

var compactNamePrefix = toLower(replace(replace(namePrefix, '-', ''), '_', ''))
var resourceToken = uniqueString(subscription().id, resourceGroup().id, namePrefix)
var accountName = take('ai${compactNamePrefix}${resourceToken}', 64)
var resolvedProjectName = take('${projectName}-${resourceToken}', 64)
var useUserAssignedIdentity = !empty(userAssignedIdentityResourceId)
var foundryIdentity = useUserAssignedIdentity ? {
  type: 'UserAssigned'
  userAssignedIdentities: {
    '${userAssignedIdentityResourceId}': {}
  }
} : {
  type: 'SystemAssigned'
}

resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: foundryIdentity
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: disableLocalAuth
    networkAcls: {
      defaultAction: publicNetworkAccess == 'Disabled' ? 'Deny' : 'Allow'
      ipRules: []
      virtualNetworkRules: []
    }
    publicNetworkAccess: publicNetworkAccess
    ...(enableManagedNetwork ? {
      networkInjections: [
        {
          scenario: 'agent'
          subnetArmId: ''
          useMicrosoftManagedNetwork: true
        }
      ]
    } : {})
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: account
  name: modelName
  dependsOn: [
    project
  ]
  sku: {
    name: modelSkuName
    capacity: modelCapacity
  }
  properties: {
    model: {
      name: modelName
      format: modelFormat
      version: modelVersion
    }
  }
}

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

output accountId string = account.id
output accountName string = account.name
output projectId string = project.id
output projectName string = project.name
output projectPrincipalId string = useUserAssignedIdentity
  ? userAssignedIdentityPrincipalId
  : project.identity.principalId
output modelDeploymentName string = modelDeployment.name
