using '../main.bicep'

// --- Deployment-specific values: replace every <...> before deploying ---
// baseName must be 3-12 lowercase alphanumeric chars. Add a short unique
// suffix so the ACR name (<baseName>acr) is globally unique, e.g. 'cicdrs1234'.
param baseName = '<your-base-name>'

// On first deploy leave this as the placeholder — runnerJobs module is
// gated behind `deployRunnerJobs=false` so the image is never read.
// After you push the image, pass --parameters deployRunnerJobs=true
// runnerImage=<baseName>acr.azurecr.io/aca-gh-runner:1.0.0 on the CLI.
param runnerImage = 'placeholder'

// Fill these in after creating your Azure OpenAI resource (see setup.md).
param azureOpenAiEndpoint = 'https://<your-aoai-resource>.openai.azure.com'
param azureOpenAiDeployment = 'gpt-5-nano'

// Your GitHub repo (once you push this project to GitHub).
param githubOwner = 'srinivasraja54'
param githubRepo = 'sustainability-cicd-rightsizing'
