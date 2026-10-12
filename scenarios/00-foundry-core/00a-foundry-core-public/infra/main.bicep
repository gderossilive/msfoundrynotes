targetScope = 'resourceGroup'

@description('Azure region for resources in this scenario.')
param location string

@description('azd environment name used to derive resource names.')
param environmentName string

@description('Model deployment name.')
param modelName string = 'gpt-4.1-mini'

@description('Model provider format.')
param modelFormat string = 'OpenAI'

@description('Model version.')
param modelVersion string = '2025-04-14'

@description('Model deployment SKU name.')
param modelSkuName string = 'GlobalStandard'

@description('Model deployment capacity in thousands of tokens per minute.')
param modelCapacity int = 30

@minLength(36)
@maxLength(36)
@description('Object ID of the signed-in Azure CLI user who deploys this lane and invokes its model. Bootstrap must provide a real Entra object ID.')
param deployerPrincipalId string

var normalizedEnvironmentName = toLower(replace(environmentName, '_', '-'))
var namePrefix = length(take(normalizedEnvironmentName, 20)) >= 3
  ? take(normalizedEnvironmentName, 20)
  : 'dev'
var compactNamePrefix = toLower(replace(replace(namePrefix, '-', ''), '_', ''))
var resourceToken = uniqueString(subscription().id, resourceGroup().id, namePrefix)
var accountName = take('ai${compactNamePrefix}${resourceToken}', 64)
var projectName = 'core-${resourceToken}'

module foundryProject '../../../../modules/core/foundry-project/main.bicep' = {
  params: {
    location: location
    namePrefix: namePrefix
    modelName: modelName
    modelFormat: modelFormat
    modelVersion: modelVersion
    modelSkuName: modelSkuName
    modelCapacity: modelCapacity
    disableLocalAuth: true
    projectName: 'core'
    projectDescription: 'The core Microsoft Foundry project for FoundryLab scenario 00.'
    projectDisplayName: 'FoundryLab core'
  }
}

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: accountName
}

resource foundryProjectResource 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' existing = {
  parent: foundryAccount
  name: projectName
}

resource deployerOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, deployerPrincipalId, 'Cognitive Services OpenAI User')
  scope: foundryAccount
  dependsOn: [
    foundryProject
  ]
  properties: {
    principalId: deployerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  }
}

resource deployerFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryProjectResource.id, deployerPrincipalId, 'Foundry User')
  scope: foundryProjectResource
  dependsOn: [
    foundryProject
  ]
  properties: {
    principalId: deployerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
  }
}

output AZURE_AI_ACCOUNT_ID string = foundryProject.outputs.accountId
output AZURE_AI_ACCOUNT_NAME string = foundryProject.outputs.accountName
output AZURE_AI_PROJECT_ID string = foundryProject.outputs.projectId
output AZURE_AI_PROJECT_NAME string = foundryProject.outputs.projectName
output AZURE_AI_PROJECT_PRINCIPAL_ID string = foundryProject.outputs.projectPrincipalId
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = foundryProject.outputs.modelDeploymentName
