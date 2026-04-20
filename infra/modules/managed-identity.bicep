// User-assigned managed identity used by:
//   - the orchestrator (to start ACA Job executions)
//   - the runner containers (to pull from ACR)
//
// Grants AcrPull on the registry. Role assignments for ACA Job control
// (Container Apps Contributor on the resource group) should be added by
// the deployer; we keep them out of this module to minimise blast radius.

@description('Identity name.')
param name string

@description('Region.')
param location string

@description('Name of the ACR to grant AcrPull on.')
param acrName string

@description('Tags.')
param tags object

resource id 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
  tags: tags
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, id.id, acrPullRoleId)
  scope: acr
  properties: {
    principalId: id.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

output identityId string = id.id
output clientId string = id.properties.clientId
output principalId string = id.properties.principalId
