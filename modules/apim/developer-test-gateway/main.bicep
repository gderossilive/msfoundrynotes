targetScope = 'resourceGroup'

@description('Azure region for the API Management Developer gateway.')
param location string

@minLength(3)
@description('Prefix used to produce deterministic resource names.')
param namePrefix string

@description('Name of the Foundry account reached through the gateway.')
param accountName string

@description('Resource ID of the non-delegated API Management subnet.')
param apimSubnetId string

@description('Publisher email recorded on the API Management instance.')
param publisherEmail string

@description('Publisher name recorded on the API Management instance.')
param publisherName string

var resourceToken = uniqueString(subscription().id, resourceGroup().id, namePrefix)
var apimName = take('apim${resourceToken}', 50)
var backendUrl = 'https://${accountName}.services.ai.azure.com/openai/v1'

resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: accountName
}

resource apim 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apimName
  location: location
  sku: {
    name: 'Developer'
    capacity: 1
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    virtualNetworkType: 'External'
    virtualNetworkConfiguration: {
      subnetResourceId: apimSubnetId
    }
  }
}

resource gatewayOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, apim.id, 'Cognitive Services OpenAI User')
  scope: account
  properties: {
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    )
  }
}

resource chatApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'foundry-chat-completions'
  properties: {
    displayName: 'Foundry Chat Completions'
    description: 'OpenAI-compatible Chat Completions gateway for private Foundry model inference.'
    path: 'openai/v1'
    protocols: [
      'https'
    ]
    subscriptionRequired: false
    serviceUrl: backendUrl
  }
}

resource chatCompletions 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: chatApi
  name: 'chat-completions'
  properties: {
    displayName: 'Chat Completions'
    method: 'POST'
    urlTemplate: '/chat/completions'
    templateParameters: []
  }
}

output apimId string = apim.id
output apimName string = apim.name
output apimPrincipalId string = apim.identity.principalId
output chatCompletionsEndpoint string = 'https://${apim.name}.azure-api.net/openai/v1/'
