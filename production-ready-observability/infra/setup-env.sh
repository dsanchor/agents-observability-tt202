#!/usr/bin/env bash
# ============================================================================
# setup-env.sh
#
# Reads deployed Azure resources from a resource group and writes the
# required environment variables to a .env file for the fraud-agents project.
#
# Usage:
#   ./setup-env.sh <RESOURCE_GROUP_NAME>
#
# Prerequisites:
#   - Azure CLI (az) installed and logged in
#   - The resource group must contain:
#       • AI Services account (Microsoft.CognitiveServices/accounts, kind=AIServices)
#       • AI Foundry project (child resource of the account)
#       • Application Insights instance
#       • Cosmos DB account
#       • Azure AI Search service
# ============================================================================
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <RESOURCE_GROUP_NAME>"
  exit 1
fi

RESOURCE_GROUP="$1"
ENV_FILE="$(dirname "$0")/../.env"

echo "🔍 Reading resources from resource group: ${RESOURCE_GROUP}"
echo ""

# ------------------------------------------------------------------
# Subscription
# ------------------------------------------------------------------
AZURE_SUBSCRIPTION_ID=$(az account show --query "id" -o tsv)
echo "  Subscription ID: ${AZURE_SUBSCRIPTION_ID}"

# ------------------------------------------------------------------
# AI Services account (kind = AIServices)
# ------------------------------------------------------------------
echo "  Looking for AI Services account..."
AI_ACCOUNT_NAME=$(az cognitiveservices account list \
  --resource-group "${RESOURCE_GROUP}" \
  --query "[?kind=='AIServices'].name | [0]" -o tsv)

if [[ -z "${AI_ACCOUNT_NAME}" ]]; then
  echo "❌ No AI Services account found in resource group ${RESOURCE_GROUP}"
  exit 1
fi
echo "  AI Services account: ${AI_ACCOUNT_NAME}"

AI_ACCOUNT_ENDPOINT=$(az cognitiveservices account show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${AI_ACCOUNT_NAME}" \
  --query "properties.endpoint" -o tsv)
echo "  AI Services endpoint: ${AI_ACCOUNT_ENDPOINT}"

# The OpenAI endpoint is the same as the AI Services endpoint for unified accounts
AZURE_OPENAI_ENDPOINT="${AI_ACCOUNT_ENDPOINT}"

# ------------------------------------------------------------------
# Model deployment name (first deployment found)
# ------------------------------------------------------------------
echo "  Looking for model deployments..."
MODEL_DEPLOYMENT_NAME=$(az cognitiveservices account deployment list \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${AI_ACCOUNT_NAME}" \
  --query "[0].name" -o tsv 2>/dev/null || echo "")

if [[ -z "${MODEL_DEPLOYMENT_NAME}" ]]; then
  MODEL_DEPLOYMENT_NAME="gpt-4.1"
  echo "  ⚠️  No model deployment found, defaulting to: ${MODEL_DEPLOYMENT_NAME}"
else
  echo "  Model deployment: ${MODEL_DEPLOYMENT_NAME}"
fi

# ------------------------------------------------------------------
# AI Foundry project (child resource of the AI Services account)
# ------------------------------------------------------------------
echo "  Looking for AI Foundry project..."
AI_FOUNDRY_PROJECT_NAME=$(az rest \
  --method GET \
  --uri "https://management.azure.com/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${AI_ACCOUNT_NAME}/projects?api-version=2025-04-01-preview" \
  --query "value[0].name" -o tsv 2>/dev/null || echo "")

if [[ -z "${AI_FOUNDRY_PROJECT_NAME}" ]]; then
  echo "  ⚠️  No AI Foundry project found. You may need to set AI_FOUNDRY_PROJECT_NAME and AI_FOUNDRY_PROJECT_ENDPOINT manually."
  AI_FOUNDRY_PROJECT_ENDPOINT=""
else
  echo "  AI Foundry project: ${AI_FOUNDRY_PROJECT_NAME}"
  # Construct the correct AI Foundry Project endpoint format
  AI_FOUNDRY_PROJECT_ENDPOINT="https://${AI_ACCOUNT_NAME}.services.ai.azure.com/api/projects/${AI_FOUNDRY_PROJECT_NAME}"
fi

# ------------------------------------------------------------------
# Application Insights (using az resource to avoid extension dependency)
# ------------------------------------------------------------------
echo "  Looking for Application Insights..."
APPINSIGHTS_NAME=$(az resource list \
  --resource-group "${RESOURCE_GROUP}" \
  --resource-type "Microsoft.Insights/components" \
  --query "[0].name" -o tsv 2>/dev/null || echo "")

APPLICATIONINSIGHTS_CONNECTION_STRING=""
if [[ -n "${APPINSIGHTS_NAME}" ]]; then
  APPLICATIONINSIGHTS_CONNECTION_STRING=$(az resource show \
    --resource-group "${RESOURCE_GROUP}" \
    --resource-type "Microsoft.Insights/components" \
    --name "${APPINSIGHTS_NAME}" \
    --query "properties.ConnectionString" -o tsv)
  echo "  Application Insights: ${APPINSIGHTS_NAME}"
else
  echo "  ⚠️  No Application Insights found. Tracing to App Insights will be disabled."
fi

# ------------------------------------------------------------------
# Cosmos DB
# ------------------------------------------------------------------
echo "  Looking for Cosmos DB account..."
COSMOS_ACCOUNT_NAME=$(az cosmosdb list \
  --resource-group "${RESOURCE_GROUP}" \
  --query "[0].name" -o tsv 2>/dev/null || echo "")

COSMOS_ENDPOINT=""
COSMOS_KEY=""
if [[ -n "${COSMOS_ACCOUNT_NAME}" ]]; then
  COSMOS_ENDPOINT=$(az cosmosdb show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${COSMOS_ACCOUNT_NAME}" \
    --query "documentEndpoint" -o tsv)
  COSMOS_KEY=$(az cosmosdb keys list \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${COSMOS_ACCOUNT_NAME}" \
    --query "primaryMasterKey" -o tsv)
  echo "  Cosmos DB account: ${COSMOS_ACCOUNT_NAME}"
else
  echo "  ⚠️  No Cosmos DB account found. Agents will run without database."
fi

# ------------------------------------------------------------------
# Azure AI Search
# ------------------------------------------------------------------
echo "  Looking for Azure AI Search service..."
SEARCH_SERVICE_NAME=$(az resource list \
  --resource-group "${RESOURCE_GROUP}" \
  --resource-type "Microsoft.Search/searchServices" \
  --query "[0].name" -o tsv 2>/dev/null || echo "")

AZURE_SEARCH_ENDPOINT=""
AZURE_SEARCH_API_KEY=""
if [[ -n "${SEARCH_SERVICE_NAME}" ]]; then
  AZURE_SEARCH_ENDPOINT="https://${SEARCH_SERVICE_NAME}.search.windows.net"
  AZURE_SEARCH_API_KEY=$(az search admin-key show \
    --resource-group "${RESOURCE_GROUP}" \
    --service-name "${SEARCH_SERVICE_NAME}" \
    --query "primaryKey" -o tsv 2>/dev/null || echo "")
  echo "  Azure AI Search: ${SEARCH_SERVICE_NAME}"
else
  echo "  ⚠️  No Azure AI Search found. Risk analyser will run without knowledge base."
fi

# ------------------------------------------------------------------
# Write .env file
# ------------------------------------------------------------------
mkdir -p "$(dirname "${ENV_FILE}")"
cat > "${ENV_FILE}" <<EOF
# =============================================================================
# Auto-generated by setup-env.sh from resource group: ${RESOURCE_GROUP}
# Generated at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# =============================================================================

# Azure Subscription
AZURE_SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID}
AZURE_RESOURCE_GROUP_NAME=${RESOURCE_GROUP}

# Azure AI Foundry / OpenAI
AI_FOUNDRY_PROJECT_ENDPOINT=${AI_FOUNDRY_PROJECT_ENDPOINT}
AI_FOUNDRY_PROJECT_NAME=${AI_FOUNDRY_PROJECT_NAME}
AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}
MODEL_DEPLOYMENT_NAME=${MODEL_DEPLOYMENT_NAME}

# Observability
APPLICATIONINSIGHTS_CONNECTION_STRING=${APPLICATIONINSIGHTS_CONNECTION_STRING}
VS_CODE_EXTENSION_PORT=4319
OTLP_ENDPOINT=http://localhost:4317

# Cosmos DB
COSMOS_ENDPOINT=${COSMOS_ENDPOINT}
COSMOS_KEY=${COSMOS_KEY}

# Azure AI Search (for regulations knowledge base)
AZURE_SEARCH_ENDPOINT=${AZURE_SEARCH_ENDPOINT}
AZURE_SEARCH_API_KEY=${AZURE_SEARCH_API_KEY}
EOF

echo ""
echo "✅ .env file written to: ${ENV_FILE}"
echo ""
echo "Variables set:"
grep -v "^#" "${ENV_FILE}" | grep -v "^$" | sed 's/=.*//' | sed 's/^/   /'
