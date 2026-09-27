using './main.bicep'

param location = readEnvironmentVariable('AZURE_LOCATION', 'italynorth')
param environmentName = readEnvironmentVariable('AZURE_ENV_NAME', 'dev')
param modelName = readEnvironmentVariable('AZURE_DEFAULT_MODEL', 'gpt-5-mini')
param modelVersion = readEnvironmentVariable('AZURE_DEFAULT_MODEL_VERSION', '2025-08-07')
param modelSkuName = readEnvironmentVariable('AZURE_DEFAULT_MODEL_SKU', 'GlobalStandard')
param modelCapacity = int(readEnvironmentVariable('AZURE_DEFAULT_MODEL_CAPACITY', '30'))
