targetScope = 'resourceGroup'

@description('Azure region for the private endpoint.')
param location string

@description('Name of the existing Microsoft Foundry account.')
param accountName string

@description('Resource ID of the private endpoint subnet.')
param privateEndpointSubnetId string

@description('Private DNS zones created for the Foundry account.')
param privateDnsZones array

var cognitiveServicesZoneId = first(filter(privateDnsZones, zone => zone.name == 'privatelink.cognitiveservices.azure.com')).id
var openAiZoneId = first(filter(privateDnsZones, zone => zone.name == 'privatelink.openai.azure.com')).id
var servicesAiZoneId = first(filter(privateDnsZones, zone => zone.name == 'privatelink.services.ai.azure.com')).id

resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: accountName
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${account.name}-private-endpoint'
  location: location
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${account.name}-connection'
        properties: {
          groupIds: [
            'account'
          ]
          privateLinkServiceId: account.id
        }
      }
    ]
  }
}

resource dnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: privateEndpoint
  name: '${account.name}-dns'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'cognitiveservices'
        properties: {
          privateDnsZoneId: cognitiveServicesZoneId
        }
      }
      {
        name: 'openai'
        properties: {
          privateDnsZoneId: openAiZoneId
        }
      }
      {
        name: 'services-ai'
        properties: {
          privateDnsZoneId: servicesAiZoneId
        }
      }
    ]
  }
}

output privateEndpointId string = privateEndpoint.id
