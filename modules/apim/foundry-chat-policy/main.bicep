targetScope = 'resourceGroup'

@description('Entra object IDs allowed to call Chat Completions. Empty denies every caller.')
param allowedPrincipalIds array = []

@minValue(0)
@maxValue(10000000)
@description('Per-caller token budget per minute. 0 keeps the gateway without a token limit.')
param tokensPerMinute int = 0

@description('Add a token metric per caller. The monitoring resources it needs are deployed by ../foundry-usage-metrics.')
param enableUsageMetrics bool = false

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

var tokenLimitTemplate = '''
    <llm-token-limit counter-key='@("tokens:" + (string)context.Variables["caller-object-id"])' tokens-per-minute="TOKENS_PER_MINUTE_PLACEHOLDER" estimate-prompt-tokens="false" tokens-consumed-header-name="x-foundrylab-consumed-tokens" remaining-tokens-header-name="x-foundrylab-remaining-tokens" />
'''

var tokenLimitPolicy = tokensPerMinute > 0
  ? replace(tokenLimitTemplate, 'TOKENS_PER_MINUTE_PLACEHOLDER', string(tokensPerMinute))
  : ''

var usageMetricTemplate = '''
    <llm-emit-token-metric namespace="foundrylab-00c">
      <dimension name="Caller" value='@((string)context.Variables["caller-object-id"])' />
    </llm-emit-token-metric>
'''

var usageMetricPolicy = enableUsageMetrics ? usageMetricTemplate : ''

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
    TOKEN_LIMIT_PLACEHOLDER
    USAGE_METRIC_PLACEHOLDER
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

@description('Rendered API Management policy for a Foundry Chat Completions API.')
output policyXml string = replace(
  replace(
    replace(
      replace(
        policy,
        'CALLER_AUTHORIZATION_PLACEHOLDER',
        replace(
          callerAuthorizationPolicy,
          'ALLOWED_PRINCIPAL_IDS_PLACEHOLDER',
          base64(string(map(allowedPrincipalIds, principalId => toLower(trim(principalId)))))
        )
      ),
      'TOKEN_LIMIT_PLACEHOLDER',
      tokenLimitPolicy
    ),
    'USAGE_METRIC_PLACEHOLDER',
    usageMetricPolicy
  ),
  'TENANT_ID_PLACEHOLDER',
  tenant().tenantId
)
