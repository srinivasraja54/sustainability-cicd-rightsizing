// Storage account + Queue for carbon-deferred workflow runs.
//
// The dispatcher (running in a GitHub Actions job with federated creds)
// enqueues a JSON message when a workflow is deferred. The carbon-scheduler
// workflow drains the queue every 10 minutes and re-triggers due runs via
// GitHub's workflow_dispatch API.
//
// RBAC: grants the orchestrator's user-assigned managed identity the built-in
// "Storage Queue Data Message Sender" and "Storage Queue Data Message Processor"
// roles so both enqueue and drain paths auth via managed identity (no SAS, no
// access keys).

@description('Storage account name (3-24 lowercase alphanumeric).')
param name string

@description('Region.')
param location string

@description('Principal ID of the UAMI used by the orchestrator + scheduler.')
param orchestratorPrincipalId string

@description('Tags.')
param tags object

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowSharedKeyAccess: false  // managed identity only
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource queue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: 'carbon-deferred'
}

// Built-in role IDs
var queueSenderRoleId = 'c6a89b2d-59bc-44d0-9896-0f6e12d7b80a'      // Storage Queue Data Message Sender
var queueProcessorRoleId = '8a0f0c08-91a1-4084-bc3d-661d67233fed'   // Storage Queue Data Message Processor

resource sender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, orchestratorPrincipalId, queueSenderRoleId)
  scope: storage
  properties: {
    principalId: orchestratorPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueSenderRoleId)
  }
}

resource processor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, orchestratorPrincipalId, queueProcessorRoleId)
  scope: storage
  properties: {
    principalId: orchestratorPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueProcessorRoleId)
  }
}

output accountName string = storage.name
output queueAccountUrl string = 'https://${storage.name}.queue.${environment().suffixes.storage}'
output queueName string = queue.name
