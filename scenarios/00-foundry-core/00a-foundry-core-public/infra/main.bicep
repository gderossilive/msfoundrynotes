targetScope = 'resourceGroup'

@description('Azure region for resources in this scenario.')
param location string

@description('azd environment name used to derive resource names.')
param environmentName string

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

var normalizedEnvironmentName = toLower(replace(environmentName, '_', '-'))
var namePrefix = length(take(normalizedEnvironmentName, 20)) >= 3
  ? take(normalizedEnvironmentName, 20)
  : 'dev'

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

output AZURE_AI_ACCOUNT_ID string = foundryProject.outputs.accountId
output AZURE_AI_ACCOUNT_NAME string = foundryProject.outputs.accountName
output AZURE_AI_PROJECT_ID string = foundryProject.outputs.projectId
output AZURE_AI_PROJECT_NAME string = foundryProject.outputs.projectName
output AZURE_AI_PROJECT_PRINCIPAL_ID string = foundryProject.outputs.projectPrincipalId
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = foundryProject.outputs.modelDeploymentName
