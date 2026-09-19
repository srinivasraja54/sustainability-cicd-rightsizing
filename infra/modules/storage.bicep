// Storage account for the two bits of state the orchestrator keeps:
//
//   Queue `carbon-deferred`  — runs waiting for a greener grid window. The
//     dispatcher enqueues a JSON message when a workflow is deferred; the
//     carbon-scheduler workflow drains it every 10 minutes and re-triggers
//     due runs via GitHub's workflow_dispatch API.
//
//   Container `sizing-cache` — one small JSON blob per (deployment, prompt,
//     workflow) hash holding the LLM's sizing verdict. This is what makes the
//     Azure OpenAI fallback cost one call per workflow *change* instead of one
//     per dispatch. See orchestrator/decision_cache.py.
//
// RBAC: grants the orchestrator's user-assigned managed identity the built-in
// "Storage Queue Data Message Sender" and "Storage Queue Data Message Processor"
// roles so both enqueue and drain paths auth via managed identity, plus
// "Storage Blob Data Contributor" for the cache read/write path (no SAS, no
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

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

// Cache entries are tiny and content-addressed, so they are never mutated —
// only added. Private access: reachable with an Entra token and nothing else.
resource sizingCache 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'sizing-cache'
  properties: {
    publicAccess: 'None'
  }
}

// Built-in role IDs
var queueSenderRoleId = 'c6a89b2d-59bc-44d0-9896-0f6e12d7b80a'      // Storage Queue Data Message Sender
var queueProcessorRoleId = '8a0f0c08-91a1-4084-bc3d-661d67233fed'   // Storage Queue Data Message Processor
var blobContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'  // Storage Blob Data Contributor

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

// Read + write on the cache container. Scoped to the container, not the
// account, so the orchestrator can never touch the queue's blobs or any
// other container that later lands here.
resource cacheContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sizingCache.id, orchestratorPrincipalId, blobContributorRoleId)
  scope: sizingCache
  properties: {
    principalId: orchestratorPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributorRoleId)
  }
}

output accountName string = storage.name
output queueAccountUrl string = 'https://${storage.name}.queue.${environment().suffixes.storage}'
output queueName string = queue.name
output sizingCacheAccountUrl string = 'https://${storage.name}.blob.${environment().suffixes.storage}'
output sizingCacheContainerName string = sizingCache.name
