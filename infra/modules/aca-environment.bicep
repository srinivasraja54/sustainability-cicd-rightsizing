// Azure Container Apps Environment using the Consumption workload
// profile. This is the unit that scales to zero — when no jobs are
// running you pay nothing for compute, only Log Analytics ingestion.

@description('Environment name.')
param name string

@description('Region.')
param location string

@description('Log Analytics workspace customer ID.')
param logAnalyticsCustomerId string

@description('Log Analytics primary shared key.')
@secure()
param logAnalyticsSharedKey string

@description('Tags.')
param tags object

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

output environmentId string = env.id
output environmentName string = env.name
