targetScope = 'resourceGroup'

@minLength(3)
@description('Prefix used to produce deterministic virtual network link names.')
param namePrefix string

@description('Resource ID of the virtual network linked to the private DNS zones.')
param vnetId string

@description('Whether to create private DNS zones for Azure AI Search, Blob Storage, and Cosmos DB.')
param includeStandardAgentZones bool = false

@description('Additional private DNS zone names required by the calling scenario.')
param additionalZoneNames array = []

var foundryZoneNames = [
  'privatelink.cognitiveservices.azure.com'
  'privatelink.openai.azure.com'
  'privatelink.services.ai.azure.com'
]
var standardAgentZoneNames = [
  'privatelink.search.windows.net'
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.documents.azure.com'
]
var zoneNames = union(
  concat(foundryZoneNames, includeStandardAgentZones ? standardAgentZoneNames : []),
  additionalZoneNames
)

resource zones 'Microsoft.Network/privateDnsZones@2024-06-01' = [
  for zoneName in zoneNames: {
    name: zoneName
    location: 'global'
  }
]

resource vnetLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [
  for (zoneName, index) in zoneNames: {
    parent: zones[index]
    name: '${namePrefix}-link'
    location: 'global'
    properties: {
      registrationEnabled: false
      virtualNetwork: {
        id: vnetId
      }
    }
  }
]

output zones array = [
  for (zoneName, index) in zoneNames: {
    name: zoneName
    id: zones[index].id
  }
]
