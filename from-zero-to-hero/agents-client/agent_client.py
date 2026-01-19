# filepath: Direct OpenAI compatible approach
import os
import sys
from openai import OpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

# Get configuration from environment variables
foundry_resource_name = os.environ.get("FOUNDRY_RESOURCE_NAME")
project_name = os.environ.get("FOUNDRY_PROJECT_NAME")
app_name = os.environ.get("AGENT_NAME", "ResearcherAgent")

# Extract foundry resource name and project name from endpoint
# Expected format: https://<resource-name>.services.ai.azure.com/api/projects/<project-name>
if not foundry_resource_name or not project_name:
    raise ValueError(
        "FOUNDRY_RESOURCE_NAME and FOUNDRY_PROJECT_NAME environment variables are required")
base_url = f"https://{foundry_resource_name}.services.ai.azure.com/api/projects/{project_name}/applications/{app_name}/protocols/openai"

openai = OpenAI(
    api_key=get_bearer_token_provider(
        DefaultAzureCredential(), "https://ai.azure.com/.default"),
    base_url=base_url,
    default_query={"api-version": "2025-11-15-preview"}
)

# Get input from command-line argument or use default
if len(sys.argv) > 1:
    input_prompt = sys.argv[1]
else:
    input_prompt = "Write a detailed article on the impact of AI in healthcare."

response = openai.responses.create(
    input=input_prompt,
)
print(f"Response output: {response.output_text}")
