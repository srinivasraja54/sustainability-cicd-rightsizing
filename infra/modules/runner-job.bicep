// A single Container Apps Job that, when started, runs one ephemeral
// GitHub Actions runner of the chosen size. The orchestrator calls
// `az containerapp job start` (or the management API) on this resource,
// passing a fresh JIT registration token via env vars.
//
// Trigger type is "Manual" — the orchestrator decides when to start.
// Replica completes after the runner picks up one job and exits.

@description('Job name.')
param name string

@description('Region.')
param location string

@description('ACA Environment resource ID.')
param environmentId string

@description('User-assigned managed identity resource ID.')
param managedIdentityId string

@description('Container image (e.g. myacr.azurecr.io/aca-gh-runner:1.0.0).')
param image string

@description('CPU cores (string, e.g. "0.5", "2.0", "4.0").')
param cpu string

@description('Memory (string, e.g. "1Gi", "4Gi", "8Gi").')
param memory string

@description('GitHub runner label this job will register with.')
param runnerLabel string

@description('GitHub org/user.')
param githubOwner string

@description('GitHub repo name.')
param githubRepo string

@description('Tags.')
param tags object

resource job 'Microsoft.App/jobs@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800       // 30 min hard cap per runner job
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: split(image, '/')[0]
          identity: managedIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'runner'
          image: image
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: [
            { name: 'GH_OWNER', value: githubOwner }
            { name: 'GH_REPO', value: githubRepo }
            { name: 'RUNNER_LABELS', value: '${runnerLabel},ephemeral' }
            // RUNNER_TOKEN is injected at start time by the orchestrator
            // via the `properties.template.containers[].env` override on
            // the job-execution start request.
          ]
        }
      ]
    }
  }
}

output jobName string = job.name
output jobId string = job.id
