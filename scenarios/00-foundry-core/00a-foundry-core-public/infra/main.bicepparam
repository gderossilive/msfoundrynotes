using './main.bicep'

param location = readEnvironmentVariable('AZURE_LOCATION', 'italynorth')
param environmentName = readEnvironmentVariable('AZURE_ENV_NAME', 'dev')
param modelName = readEnvironmentVariable('AZURE_DEFAULT_MODEL', 'gpt-4.1-mini')
param modelVersion = readEnvironmentVariable('AZURE_DEFAULT_MODEL_VERSION', '2025-04-14')
param modelSkuName = readEnvironmentVariable('AZURE_DEFAULT_MODEL_SKU', 'GlobalStandard')
param modelCapacity = int(readEnvironmentVariable('AZURE_DEFAULT_MODEL_CAPACITY', '30'))
// The bootstrap script replaces this non-assignable sentinel with the signed-in user's Object ID.
param deployerPrincipalId = readEnvironmentVariable('AZURE_DEPLOYER_PRINCIPAL_ID', '00000000-0000-0000-0000-000000000000')
