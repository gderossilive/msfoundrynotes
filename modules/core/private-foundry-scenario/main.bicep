targetScope = 'resourceGroup'

@description('Azure region for the Foundry resources and private endpoint.')
param location string

@minLength(3)
@description('Prefix used to produce deterministic resource names.')
param namePrefix string

@description('Address space for the customer-managed virtual network.')
param vnetAddressSpace string

@description('Address prefix for the private endpoint subnet.')
param privateEndpointSubnetPrefix string

@description('Whether to create a dedicated subnet and NSG for an API Management Developer gateway.')
param enableApimDeveloperGateway bool = false

@description('Address prefix for the API Management Developer gateway subnet.')
param apimSubnetPrefix string = '10.20.2.0/26'

@description('Configure managed network injection on the Foundry account for a separately provisioned managed network.')
param enableManagedNetwork bool = false

@description('Model deployment name.')
param modelName string

@description('Model provider format.')
param modelFormat string = 'OpenAI'

@description('Model version.')
param modelVersion string

@description('Model deployment SKU name.')
param modelSkuName string

@minValue(1)
@description('Model deployment capacity in the selected SKU capacity units.')
param modelCapacity int

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${namePrefix}-vnet'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressSpace
      ]
    }
    subnets: [
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: privateEndpointSubnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

resource privateEndpointSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: network
  name: 'private-endpoints'
}

resource apimNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = if (enableApimDeveloperGateway) {
  name: '${namePrefix}-apim-nsg'
  location: location
  properties: {
    securityRules: [
      {
        name: 'allow-client-https'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '443'
        }
      }
      {
        name: 'allow-apim-management'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'ApiManagement'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '3443'
        }
      }
      {
        name: 'allow-azure-load-balancer'
        properties: {
          priority: 120
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'AzureLoadBalancer'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '6390'
        }
      }
      {
        name: 'allow-certificate-validation'
        properties: {
          priority: 100
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRange: '80'
        }
      }
      {
        name: 'allow-storage'
        properties: {
          priority: 110
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Storage'
          destinationPortRange: '443'
        }
      }
      {
        name: 'allow-sql'
        properties: {
          priority: 120
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Sql'
          destinationPortRange: '1433'
        }
      }
      {
        name: 'allow-key-vault'
        properties: {
          priority: 130
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzureKeyVault'
          destinationPortRange: '443'
        }
      }
      {
        name: 'allow-monitor'
        properties: {
          priority: 140
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzureMonitor'
          destinationPortRange: '1886'
        }
      }
      {
        name: 'allow-monitor-https'
        properties: {
          priority: 150
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzureMonitor'
          destinationPortRange: '443'
        }
      }
    ]
  }
}

resource apimSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = if (enableApimDeveloperGateway) {
  parent: network
  name: 'apim'
  properties: {
    addressPrefix: apimSubnetPrefix
    networkSecurityGroup: {
      id: apimNsg.id
    }
  }
}

module dns '../../private-network/foundry-private-dns/main.bicep' = {
  params: {
    namePrefix: namePrefix
    vnetId: network.id
  }
}

module foundryProject '../foundry-project/main.bicep' = {
  params: {
    location: location
    namePrefix: namePrefix
    modelName: modelName
    modelFormat: modelFormat
    modelVersion: modelVersion
    modelSkuName: modelSkuName
    modelCapacity: modelCapacity
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    enableManagedNetwork: enableManagedNetwork
    projectName: 'core'
    projectDescription: 'A Microsoft Foundry Core project with private inbound access.'
    projectDisplayName: 'FoundryLab private core'
  }
}

module privateEndpoint '../../private-network/foundry-account-private-endpoint/main.bicep' = {
  params: {
    location: location
    accountName: foundryProject.outputs.accountName
    privateEndpointSubnetId: privateEndpointSubnet.id
    privateDnsZones: dns.outputs.zones
  }
}

output accountId string = foundryProject.outputs.accountId
output accountName string = foundryProject.outputs.accountName
output projectId string = foundryProject.outputs.projectId
output projectName string = foundryProject.outputs.projectName
output projectPrincipalId string = foundryProject.outputs.projectPrincipalId
output modelDeploymentName string = foundryProject.outputs.modelDeploymentName
output vnetId string = network.id
output privateEndpointSubnetId string = privateEndpointSubnet.id
output privateEndpointId string = privateEndpoint.outputs.privateEndpointId
output apimSubnetId string = enableApimDeveloperGateway ? apimSubnet.id : ''
