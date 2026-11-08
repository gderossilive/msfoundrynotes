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

@description('Opt in to model diagnostics and client tracing. The default keeps the minimal 00a deployment unchanged.')
param enableMonitoring bool = false

@minLength(36)
@maxLength(36)
@description('Object ID of the signed-in Azure CLI user who deploys this lane and invokes its model. Bootstrap must provide a real Entra object ID.')
param deployerPrincipalId string

@description('Opt in to a public API Management gateway in front of the model. The account stays public and the deployer keeps a direct role, so the gateway is an extra door, not the only one. Billed while it exists. The default keeps the minimal 00a deployment unchanged.')
param enableGateway bool = false

@allowed([
  'BasicV2'
  'StandardV2'
])
@description('API Management v2 tier of the optional gateway.')
param gatewaySkuName string = 'BasicV2'

@description('Publisher email recorded on the optional gateway.')
param gatewayPublisherEmail string = 'platform-team@example.com'

@description('Publisher name recorded on the optional gateway.')
param gatewayPublisherName string = 'FoundryLab platform team'

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

resource deployerFoundryOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryProjectResource.id, deployerPrincipalId, 'Foundry Owner')
  scope: foundryProjectResource
  dependsOn: [
    foundryProject
  ]
  properties: {
    principalId: deployerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'c883944f-8b7b-4483-af10-35834be79c4a')
  }
}

module monitoring './monitoring.bicep' = if (enableMonitoring) {
  params: {
    location: location
    namePrefix: namePrefix
    accountName: accountName
    deployerPrincipalId: deployerPrincipalId
  }
  dependsOn: [
    foundryProject
  ]
}

module gateway '../../../../modules/apim/foundry-public-gateway/main.bicep' = if (enableGateway) {
  params: {
    location: location
    namePrefix: namePrefix
    accountName: accountName
    publisherEmail: gatewayPublisherEmail
    publisherName: gatewayPublisherName
    skuName: gatewaySkuName
  }
  dependsOn: [
    foundryProject
  ]
}

output AZURE_AI_ACCOUNT_ID string = foundryProject.outputs.accountId
output AZURE_AI_ACCOUNT_NAME string = foundryProject.outputs.accountName
output AZURE_AI_PROJECT_ID string = foundryProject.outputs.projectId
output AZURE_AI_PROJECT_NAME string = foundryProject.outputs.projectName
output AZURE_AI_PROJECT_PRINCIPAL_ID string = foundryProject.outputs.projectPrincipalId
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = foundryProject.outputs.modelDeploymentName
output AZURE_MONITORING_ENABLED bool = enableMonitoring
output AZURE_MONITORING_WORKSPACE_ID string = enableMonitoring ? monitoring!.outputs.workspaceId : ''
output AZURE_MONITORING_APPLICATION_INSIGHTS_ID string = enableMonitoring ? monitoring!.outputs.appInsightsId : ''
output AZURE_GATEWAY_ENABLED bool = enableGateway
output AZURE_APIM_ID string = enableGateway ? gateway!.outputs.apimId : ''
output AZURE_APIM_NAME string = enableGateway ? gateway!.outputs.apimName : ''
output AZURE_APIM_PRINCIPAL_ID string = enableGateway ? gateway!.outputs.apimPrincipalId : ''
output AZURE_APIM_CHAT_COMPLETIONS_ENDPOINT string = enableGateway ? gateway!.outputs.chatCompletionsEndpoint : ''
