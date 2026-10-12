using './main.bicep'

param location = readEnvironmentVariable('AZURE_LOCATION', 'italynorth')
param environmentName = readEnvironmentVariable('AZURE_ENV_NAME', 'dev')
param apimPublisherEmail = readEnvironmentVariable('AZURE_APIM_PUBLISHER_EMAIL', 'platform-team@example.com')
param apimPublisherName = readEnvironmentVariable('AZURE_APIM_PUBLISHER_NAME', 'FoundryLab platform team')
param modelName = readEnvironmentVariable('AZURE_DEFAULT_MODEL', 'gpt-5-mini')
param modelVersion = readEnvironmentVariable('AZURE_DEFAULT_MODEL_VERSION', '2025-08-07')
param modelSkuName = readEnvironmentVariable('AZURE_DEFAULT_MODEL_SKU', 'GlobalStandard')
param modelCapacity = int(readEnvironmentVariable('AZURE_DEFAULT_MODEL_CAPACITY', '30'))
