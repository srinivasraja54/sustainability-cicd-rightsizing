using '../main.bicep'

// --- Sandbox-specific values (user 2189120, RG ODL-Cognizant-Hackathon-2189120-02) ---
// baseName must be 3-12 lowercase alphanumeric chars. We use the lab ID
// as a suffix so the ACR name (<baseName>acr) is globally unique.
param baseName = 'cicdrs2189120'

// On first deploy leave this as the placeholder — runnerJobs module is
// gated behind `deployRunnerJobs=false` so the image is never read.
// After you push the image, pass --parameters deployRunnerJobs=true
// runnerImage=cicdrs2189120acr.azurecr.io/aca-gh-runner:1.0.0 on the CLI.
param runnerImage = 'placeholder'

// Fill these in after creating your Azure OpenAI resource (see setup.md).
param azureOpenAiEndpoint = 'https://cicdrs2189120-aoai.openai.azure.com'
param azureOpenAiDeployment = 'gpt-5-nano'

// Your GitHub repo (once you push this project to GitHub).
param githubOwner = 'srinivasraja54'
param githubRepo = 'sustainability-cicd-rightsizing'
