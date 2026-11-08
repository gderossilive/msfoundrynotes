targetScope = 'resourceGroup'

@description('Name of the existing API Management gateway.')
param apimName string

@description('Entra object IDs allowed to call Chat Completions. Empty denies every caller.')
param allowedPrincipalIds array = []

@minValue(0)
@maxValue(10000000)
@description('Per-caller token budget per minute. 0 keeps the gateway without a token limit.')
param tokensPerMinute int = 0

@description('Emit a token metric per caller to Application Insights and create the monitoring resources it needs.')
param enableUsageMetrics bool = false

resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimName
}

resource chatApi 'Microsoft.ApiManagement/service/apis@2024-05-01' existing = {
  parent: apim
  name: 'foundry-chat-completions'
}

module policyContent '../../../../modules/apim/foundry-chat-policy/main.bicep' = {
  params: {
    allowedPrincipalIds: allowedPrincipalIds
    tokensPerMinute: tokensPerMinute
    enableUsageMetrics: enableUsageMetrics
  }
}

module usageMetrics '../../../../modules/apim/foundry-usage-metrics/main.bicep' = if (enableUsageMetrics) {
  params: {
    location: resourceGroup().location
    apimName: apimName
  }
}

resource chatPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: chatApi
  name: 'policy'
  dependsOn: [
    usageMetrics
  ]
  properties: {
    format: 'rawxml'
    value: policyContent.outputs.policyXml
  }
}

output policyId string = chatPolicy.id
output usageWorkspaceId string = enableUsageMetrics ? usageMetrics!.outputs.workspaceId : ''
output usageWorkspaceCustomerId string = enableUsageMetrics ? usageMetrics!.outputs.workspaceCustomerId : ''
