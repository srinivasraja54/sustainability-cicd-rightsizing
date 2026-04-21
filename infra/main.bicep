// Top-level Bicep for the right-sizing CI/CD demo.
// Deploys:
//   - Log Analytics workspace (required by Container Apps)
//   - Azure Container Registry (for the runner image)
//   - User-assigned managed identity used by the orchestrator + runners
//   - Container Apps Environment (consumption profile, scale-to-zero)
//   - Three Container Apps Jobs, one per size tier (small/medium/large)
//
// All three jobs share the same image; they differ only in CPU/memory
// allocation. The orchestrator picks which one to "start" per pipeline.

targetScope = 'resourceGroup'

@description('Base name used for all resources (3-20 chars, lowercase).')
@minLength(3)
@maxLength(20)
param baseName string = 'cicdrs'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Container image reference for the GitHub Actions runner. Only used when deployRunnerJobs=true.')
param runnerImage string = 'ghcr.io/your-org/aca-gh-runner:latest'

@description('Two-phase deploy: false on the first run (image does not exist yet), true on the second run after the image is pushed to ACR.')
param deployRunnerJobs bool = false

@description('Azure OpenAI endpoint URL (https://<resource>.openai.azure.com).')
param azureOpenAiEndpoint string

@description('Azure OpenAI deployment name to call (e.g. gpt-4o-mini).')
param azureOpenAiDeployment string = 'gpt-4o-mini'

@description('GitHub org or user that owns the repo.')
param githubOwner string

@description('GitHub repo name.')
param githubRepo string

var tags = {
  project: 'sustainability-cicd-rightsizing'
  managedBy: 'bicep'
  costCenter: 'hackathon'
}

// --- Shared infrastructure ---

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${baseName}-law'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: '${baseName}acr'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

module identity './modules/managed-identity.bicep' = {
  name: 'identity'
  params: {
    name: '${baseName}-id'
    location: location
    acrName: acr.name
    tags: tags
  }
}

module env './modules/aca-environment.bicep' = {
  name: 'aca-env'
  params: {
    name: '${baseName}-env'
    location: location
    logAnalyticsCustomerId: law.properties.customerId
    logAnalyticsSharedKey: law.listKeys().primarySharedKey
    tags: tags
  }
}

module storage './modules/storage.bicep' = {
  name: 'carbon-queue-storage'
  params: {
    // Storage account names are globally unique, 3-24 lowercase alphanumeric.
    // Replace hyphens from baseName to respect that.
    name: toLower(replace('${baseName}sa', '-', ''))
    location: location
    orchestratorPrincipalId: identity.outputs.principalId
    tags: tags
  }
}

// --- Three runner jobs, one per size tier ---

var sizes = [
  {
    name: 'small'
    cpu: '0.5'
    memory: '1Gi'
    label: 'aca-small'
  }
  {
    name: 'medium'
    cpu: '2.0'
    memory: '4Gi'
    label: 'aca-medium'
  }
  {
    name: 'large'
    cpu: '4.0'
    memory: '8Gi'
    label: 'aca-large'
  }
]

module runnerJobs './modules/runner-job.bicep' = [for s in sizes: if (deployRunnerJobs) {
  name: 'runner-${s.name}'
  params: {
    name: '${baseName}-runner-${s.name}'
    location: location
    environmentId: env.outputs.environmentId
    managedIdentityId: identity.outputs.identityId
    image: runnerImage
    cpu: s.cpu
    memory: s.memory
    runnerLabel: s.label
    githubOwner: githubOwner
    githubRepo: githubRepo
    tags: union(tags, { sizeTier: s.name })
  }
}]

// --- Outputs ---

output environmentName string = env.outputs.environmentName
output identityClientId string = identity.outputs.clientId
output acrLoginServer string = acr.properties.loginServer
output runnerJobNames array = deployRunnerJobs ? map(sizes, s => '${baseName}-runner-${s.name}') : []
output azureOpenAiEndpointOut string = azureOpenAiEndpoint
output azureOpenAiDeploymentOut string = azureOpenAiDeployment
output carbonQueueAccountUrl string = storage.outputs.queueAccountUrl
