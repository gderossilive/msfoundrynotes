targetScope = 'resourceGroup'

@description('Azure region for the monitoring resources.')
param location string

@description('Name of the existing API Management Developer gateway.')
param apimName string

@description('Name of the existing gateway API that receives the usage diagnostics.')
param apiName string = 'foundry-chat-completions'

var resourceToken = uniqueString(subscription().id, resourceGroup().id, apimName)
var monitoringMetricsPublisherRoleId = '3913510d-42f4-4e42-8a64-420c390055eb'

resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimName
}

resource chatApi 'Microsoft.ApiManagement/service/apis@2024-05-01' existing = {
  parent: apim
  name: apiName
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law${resourceToken}'
  location: location
  properties: {
    retentionInDays: 30
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi${resourceToken}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    DisableLocalAuth: true
  }
}

resource gatewayPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appInsights.id, apim.id, monitoringMetricsPublisherRoleId)
  scope: appInsights
  properties: {
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      monitoringMetricsPublisherRoleId
    )
  }
}

resource logger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: apim
  name: 'usage-appinsights'
  dependsOn: [
    gatewayPublisher
  ]
  properties: {
    loggerType: 'applicationInsights'
    description: 'Token usage per caller, sent with the gateway managed identity.'
    resourceId: appInsights.id
    credentials: {
      connectionString: appInsights.properties.ConnectionString
      identityClientId: 'systemAssigned'
    }
  }
}

// No request or response bodies are configured, so prompts and answers are never logged.
resource diagnostic 'Microsoft.ApiManagement/service/apis/diagnostics@2024-05-01' = {
  parent: chatApi
  name: 'applicationinsights'
  properties: {
    loggerId: logger.id
    alwaysLog: 'allErrors'
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
    verbosity: 'error'
    metrics: true
  }
}

output workspaceId string = workspace.id
output workspaceCustomerId string = workspace.properties.customerId
output appInsightsId string = appInsights.id
