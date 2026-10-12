targetScope = 'resourceGroup'

@description('Name of the existing API Management Developer gateway.')
param apimName string

@description('Entra object IDs allowed to call Chat Completions. Empty denies every caller.')
param allowedPrincipalIds array = []

var callerAuthorizationPolicy = '''
    <set-variable name="caller-object-id" value='@(((Jwt)context.Variables["caller-token"]).Claims.GetValueOrDefault("oid", "").ToLowerInvariant())' />
    <choose>
      <when condition='@(string.IsNullOrEmpty((string)context.Variables["caller-object-id"]) || !JArray.Parse(System.Text.Encoding.UTF8.GetString(Convert.FromBase64String("ALLOWED_PRINCIPAL_IDS_PLACEHOLDER"))).Values&lt;string&gt;().Contains((string)context.Variables["caller-object-id"]))'>
        <return-response>
          <set-status code="403" reason="Forbidden" />
        </return-response>
      </when>
    </choose>
'''

var policy = '''
<policies>
  <inbound>
    <base />
    <validate-azure-ad-token tenant-id="TENANT_ID_PLACEHOLDER" output-token-variable-name="caller-token" failed-validation-httpcode="401" failed-validation-error-message="Unauthorized. Present a Microsoft Entra ID token.">
      <audiences>
        <audience>https://ai.azure.com</audience>
      </audiences>
    </validate-azure-ad-token>
    CALLER_AUTHORIZATION_PLACEHOLDER
    <authentication-managed-identity resource="https://cognitiveservices.azure.com" output-token-variable-name="gateway-access-token" ignore-error="false" />
    <set-header name="Authorization" exists-action="override">
      <value>@("Bearer " + (string)context.Variables["gateway-access-token"])</value>
    </set-header>
    <set-header name="api-key" exists-action="delete" />
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
    <set-header name="x-foundrylab-gateway" exists-action="override">
      <value>@(context.Deployment.ServiceName)</value>
    </set-header>
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
'''

resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimName
}

resource chatApi 'Microsoft.ApiManagement/service/apis@2024-05-01' existing = {
  parent: apim
  name: 'foundry-chat-completions'
}

resource chatPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: chatApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: replace(
      replace(
        policy,
        'CALLER_AUTHORIZATION_PLACEHOLDER',
        replace(
          callerAuthorizationPolicy,
          'ALLOWED_PRINCIPAL_IDS_PLACEHOLDER',
          base64(string(map(allowedPrincipalIds, principalId => toLower(trim(principalId)))))
        )
      ),
      'TENANT_ID_PLACEHOLDER',
      tenant().tenantId
    )
  }
}

output policyId string = chatPolicy.id
