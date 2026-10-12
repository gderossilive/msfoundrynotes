targetScope = 'resourceGroup'

@description('Azure region for resources in this scenario.')
param location string

@description('azd environment name used to derive resource names.')
param environmentName string

@description('Address space for the customer-managed virtual network.')
param vnetAddressSpace string = '10.20.0.0/16'

@description('CIDR range for the private endpoint subnet.')
param privateEndpointSubnetPrefix string = '10.20.1.0/24'

@description('CIDR range for the API Management Developer gateway subnet.')
param apimSubnetPrefix string = '10.20.2.0/26'

@description('Publisher email recorded on the API Management Developer gateway.')
param apimPublisherEmail string

@description('Publisher name recorded on the API Management Developer gateway.')
param apimPublisherName string

@description('Model deployment name.')
param modelName string = 'gpt-5-mini'

@description('Model provider format.')
param modelFormat string = 'OpenAI'

@description('Model version.')
param modelVersion string = '2025-08-07'

@description('Model deployment SKU name.')
param modelSkuName string = 'GlobalStandard'

@description('Model deployment capacity in thousands of tokens per minute.')
param modelCapacity int = 30

var normalizedEnvironmentName = toLower(replace(environmentName, '_', '-'))
var namePrefix = length(take(normalizedEnvironmentName, 20)) >= 3
  ? take(normalizedEnvironmentName, 20)
  : 'dev'

module core '../../../../modules/core/private-foundry-scenario/main.bicep' = {
  params: {
    location: location
    namePrefix: namePrefix
    vnetAddressSpace: vnetAddressSpace
    privateEndpointSubnetPrefix: privateEndpointSubnetPrefix
    enableApimDeveloperGateway: true
    apimSubnetPrefix: apimSubnetPrefix
    modelName: modelName
    modelFormat: modelFormat
    modelVersion: modelVersion
    modelSkuName: modelSkuName
    modelCapacity: modelCapacity
  }
}

module gateway '../../../../modules/apim/developer-test-gateway/main.bicep' = {
  params: {
    location: location
    namePrefix: namePrefix
    accountName: core.outputs.accountName
    apimSubnetId: core.outputs.apimSubnetId
    publisherEmail: apimPublisherEmail
    publisherName: apimPublisherName
  }
}

output AZURE_AI_ACCOUNT_ID string = core.outputs.accountId
output AZURE_AI_ACCOUNT_NAME string = core.outputs.accountName
output AZURE_AI_PROJECT_ID string = core.outputs.projectId
output AZURE_AI_PROJECT_NAME string = core.outputs.projectName
output AZURE_AI_PROJECT_PRINCIPAL_ID string = core.outputs.projectPrincipalId
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = core.outputs.modelDeploymentName
output AZURE_VNET_ID string = core.outputs.vnetId
output AZURE_PRIVATE_ENDPOINT_SUBNET_ID string = core.outputs.privateEndpointSubnetId
output AZURE_AI_PRIVATE_ENDPOINT_ID string = core.outputs.privateEndpointId
output AZURE_APIM_SUBNET_ID string = core.outputs.apimSubnetId
output AZURE_APIM_ID string = gateway.outputs.apimId
output AZURE_APIM_NAME string = gateway.outputs.apimName
output AZURE_APIM_PRINCIPAL_ID string = gateway.outputs.apimPrincipalId
output AZURE_APIM_CHAT_COMPLETIONS_ENDPOINT string = gateway.outputs.chatCompletionsEndpoint
