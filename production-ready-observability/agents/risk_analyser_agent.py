import asyncio
import logging
import os
from typing import Annotated
import dotenv
from agent_framework import ChatAgent
from agent_framework.observability import enable_instrumentation, get_tracer
from agent_framework.openai import OpenAIChatClient
from azure.monitor.opentelemetry import configure_azure_monitor
from azure.ai.projects.aio import AIProjectClient
from azure.cosmos import CosmosClient
from azure.identity.aio import AzureCliCredential
from openai import AsyncAzureOpenAI
from opentelemetry.trace import SpanKind
from opentelemetry.trace.span import format_trace_id
from pydantic import Field

"""
Risk Analyser Agent with Foundry Tracing and Knowledge Retrieval
This agent evaluates financial transactions for potential fraud using regulations and policies
stored in Azure AI Search knowledge base via AzureAISearchContextProvider.

Knowledge Base Integration:
- Uses AzureAISearchContextProvider in 'agentic' mode for seamless knowledge base integration
- The knowledge base 'regulations-knowledge-base' contains fraud detection rules and compliance requirements
- The agent can query regulations automatically during risk analysis
"""

# For loading environment variables
dotenv.load_dotenv()

logger = logging.getLogger(__name__)

# Configuration
cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT")
cosmos_key = os.environ.get("COSMOS_KEY")

# Initialize Cosmos DB clients (conditional)
transactions_container = None
if cosmos_endpoint and cosmos_key:
    try:
        cosmos_client = CosmosClient(cosmos_endpoint, cosmos_key)
        database = cosmos_client.get_database_client("FinancialComplianceDB")
        transactions_container = database.get_container_client("Transactions")
        logger.info("Cosmos DB connected successfully")
    except Exception as e:
        logger.warning(f"Could not connect to Cosmos DB: {e}. Using basic risk analysis.")
else:
    logger.warning("Cosmos DB credentials not found. Using basic risk analysis. Set COSMOS_ENDPOINT and COSMOS_KEY in .env file.")

# Risk factor configuration
RISK_FACTORS = {
    "high_risk_countries": ["NG", "IR", "RU", "KP"],
    "high_amount_threshold_usd": 10000,
    "suspicious_account_age_days": 30,
    "low_device_trust_threshold": 0.5
}


async def analyze_transaction_risk(
    transaction_id: Annotated[str, Field(description="The transaction ID to analyze for risk.")],
    customer_country: Annotated[str, Field(description="Customer's country code (e.g., US, CN).")],
    amount_usd: Annotated[float, Field(description="Transaction amount in USD.")],
    account_age_days: Annotated[int, Field(description="Customer account age in days.")],
) -> str:
    """Analyze a transaction for fraud risk based on risk factors and return risk score with reasoning."""
    try:
        risk_score = 0
        risk_factors_found = []
        
        # Check high risk country
        if customer_country in RISK_FACTORS["high_risk_countries"]:
            risk_score += 30
            risk_factors_found.append(f"High-risk country: {customer_country}")
        
        # Check high amount
        if amount_usd >= RISK_FACTORS["high_amount_threshold_usd"]:
            risk_score += 25
            risk_factors_found.append(f"High amount: ${amount_usd}")
        
        # Check suspicious account age
        if account_age_days <= RISK_FACTORS["suspicious_account_age_days"]:
            risk_score += 20
            risk_factors_found.append(f"New account: {account_age_days} days old")
        
        # Check transaction patterns from database (if available)
        if transactions_container:
            try:
                query = f"SELECT * FROM c WHERE c.id = '{transaction_id}'"
                items = list(transactions_container.query_items(
                    query=query,
                    enable_cross_partition_query=True
                ))
                
                if items:
                    txn = items[0]
                    # Add more risk factors based on transaction data
                    if txn.get('device_trust_score', 1.0) < RISK_FACTORS["low_device_trust_threshold"]:
                        risk_score += 15
                        risk_factors_found.append(f"Low device trust score: {txn.get('device_trust_score')}")
            except Exception as db_error:
                logger.warning(f"Could not query transaction from database: {db_error}")
        
        # Determine risk level
        if risk_score >= 75:
            risk_level = "High"
        elif risk_score >= 40:
            risk_level = "Medium"
        else:
            risk_level = "Low"
        
        result = f"Risk Score: {risk_score}/100\n"
        result += f"Risk Level: {risk_level}\n"
        result += f"Risk Factors:\n" + "\n".join(f"  - {factor}" for factor in risk_factors_found) if risk_factors_found else "  - None identified"
        
        return result
    except Exception as e:
        logger.error(f"Error analyzing transaction risk: {e}")
        return f"Error analyzing transaction {transaction_id}: {str(e)}"


async def main():
    async with (
        AzureCliCredential() as credential,
        AIProjectClient(
            endpoint=os.environ["AI_FOUNDRY_PROJECT_ENDPOINT"],
            subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
            resource_group_name=os.environ["AZURE_RESOURCE_GROUP_NAME"],
            project_name=os.environ["AI_FOUNDRY_PROJECT_NAME"],
            credential=credential
        ) as project_client,
    ):
        # Enable tracing and configure telemetry
        try:
            conn_string = await project_client.telemetry.get_application_insights_connection_string()
        except Exception as e:
            logger.warning(
                f"Could not get Application Insights connection string from Azure AI Project: {e}. "
                "Using APPLICATIONINSIGHTS_CONNECTION_STRING from environment."
            )
            conn_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
            if not conn_string:
                logger.error("No Application Insights connection string found. Please set APPLICATIONINSIGHTS_CONNECTION_STRING.")
                return
        
        # Configure Azure Monitor for Application Insights telemetry
        configure_azure_monitor(
            connection_string=conn_string,
            enable_live_metrics=True,
        )
        
        # Enable agent framework instrumentation
        enable_instrumentation(enable_sensitive_data=True)
        
        # Register agent in Azure AI Foundry portal
        try:
            from azure.ai.projects.models import PromptAgentDefinition, FunctionTool, FileSearchTool
            import json
            import tempfile
            
            # Get current agent version and increment
            current_version = 0
            try:
                async for agent in project_client.agents.list():
                    if agent.name == "RiskAnalyserAgent" and agent.metadata:
                        current_version = max(current_version, float(agent.metadata.get("version", "0")))
            except:
                pass
            
            new_version = current_version + 1
            
            # Find or create vector store with regulations data
            vector_store_id = None
            vector_store_name = "regulations-knowledge-base"
            
            try:
                # First, try to find existing vector store
                async for vs in project_client.agents.list_vector_stores():
                    if vs.name == vector_store_name:
                        vector_store_id = vs.id
                        logger.info(f"Found existing vector store: {vs.name} (ID: {vector_store_id})")
                        break
                
                # If not found, create vector store and upload regulations data
                if not vector_store_id:
                    logger.info(f"Creating vector store and uploading regulations data...")
                    
                    # Load regulations data from Cosmos DB (already indexed in Azure AI Search)
                    from azure.search.documents import SearchClient
                    from azure.core.credentials import AzureKeyCredential
                    
                    search_client = SearchClient(
                        endpoint=os.environ.get("AZURE_SEARCH_ENDPOINT"),
                        index_name="regulations-policies",
                        credential=AzureKeyCredential(os.environ.get("AZURE_SEARCH_API_KEY"))
                    )
                    
                    # Fetch regulations from Azure AI Search index
                    results = list(search_client.search("*", top=1000))
                    
                    # Create temp file with regulations
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as temp_file:
                        for doc in results:
                            temp_file.write(f"Title: {doc.get('title', 'N/A')}\n")
                            temp_file.write(f"Category: {doc.get('category', 'N/A')}\n")
                            temp_file.write(f"Content: {doc.get('content', 'N/A')}\n")
                            temp_file.write("\n" + "="*80 + "\n\n")
                        temp_file_path = temp_file.name
                    
                    # Upload file and create vector store
                    with open(temp_file_path, 'rb') as f:
                        file = await project_client.agents.upload_file_and_poll(f, purpose="assistants")
                    
                    vector_store = await project_client.agents.create_vector_store_and_poll(
                        file_ids=[file.id],
                        name=vector_store_name
                    )
                    vector_store_id = vector_store.id
                    logger.info(f"Created vector store: {vector_store_name} (ID: {vector_store_id})")
                    
                    # Clean up temp file
                    import os as os_module
                    os_module.unlink(temp_file_path)
                    
            except Exception as e:
                logger.warning(f"Could not create/find vector store: {e}")
            
            # Build tools list
            tools_list = [
                FunctionTool(
                    name="analyze_transaction_risk",
                    description="Analyze a transaction for fraud risk based on risk factors and return risk score with reasoning.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "transaction_id": {"type": "string", "description": "The transaction ID to analyze for risk."},
                            "customer_country": {"type": "string", "description": "Customer's country code (e.g., US, CN)."},
                            "amount_usd": {"type": "number", "description": "Transaction amount in USD."},
                            "account_age_days": {"type": "integer", "description": "Customer account age in days."}
                        },
                        "required": ["transaction_id", "customer_country", "amount_usd", "account_age_days"]
                    }
                )
            ]
            
            # Add file search tool if vector store found
            if vector_store_id:
                tools_list.append(FileSearchTool(vector_store_ids=[vector_store_id]))
                logger.info(f"Added FileSearchTool with vector store {vector_store_id}")
            
            # Create agent definition with knowledge base integration
            definition = PromptAgentDefinition(
                model=os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini"),
                instructions="""You are a Risk Analyser Agent evaluating financial transactions for potential fraud.
Given a normalized transaction and customer profile, your task is to:
- Apply fraud detection logic using rule-based checks and regulatory compliance data
- Search the knowledge base 'regulations-knowledge-base' for relevant regulations and policies
- Assign a fraud risk score from 0 to 100
- Generate human-readable reasoning behind the score

When analyzing risk:
1. Search for relevant fraud detection regulations and compliance requirements in the knowledge base
2. Use analyze_transaction_risk to calculate risk scores based on transaction factors
3. Cross-reference findings with regulatory policies from the knowledge base

Consider risk factors like high-risk countries, high amounts, suspicious account age, and device trust scores.

Output should include:
- risk_score: integer (0-100)
- risk_level: [Low, Medium, High]
- reason: a brief explainable summary with references to relevant regulations or policies from the knowledge base""",
                tools=tools_list
            )
            
            # Create new version of the agent with knowledge base integration via context provider
            logger.info(f"Creating agent version {new_version}")
            
            try:
                registered_agent = await project_client.agents.create_version(
                    agent_name="RiskAnalyserAgent",
                    definition=definition,
                    description=f"Risk analysis agent v{new_version} with Azure AI Search knowledge base via AzureAISearchContextProvider",
                    metadata={
                        "version": str(new_version), 
                        "framework": "agent-framework", 
                        "observability": "enabled", 
                        "knowledge_base": "regulations-knowledge-base"
                    }
                )
                logger.info(f"Agent version {new_version} created successfully")
            except Exception as create_error:
                # If version creation fails, try to get the agent
                async for agent in project_client.agents.list():
                    if agent.name == "RiskAnalyserAgent":
                        registered_agent = agent
                        break
            
        except Exception as e:
            logger.warning(f"Could not register agent in portal: {e}")

        # Test queries
        queries = [
            "What are the main KYC regulations I should consider for fraud detection?",
        ]

        with get_tracer().start_as_current_span("Risk Analyser Agent Chat", kind=SpanKind.CLIENT) as current_span:
            print(f"Trace ID: {format_trace_id(current_span.get_span_context().trace_id)}")

            # Create Azure OpenAI client with token-based authentication
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            
            # Use sync credential for token provider
            sync_credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                sync_credential,
                "https://cognitiveservices.azure.com/.default"
            )
            
            azure_openai_client = AsyncAzureOpenAI(
                azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
                azure_ad_token_provider=token_provider,
                api_version="2024-10-21"
            )

            # Create agent without search context (Azure Search not configured)
            agent = ChatAgent(
                chat_client=OpenAIChatClient(
                    async_client=azure_openai_client,
                    model_id=os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4.1"),
                ),
                tools=[analyze_transaction_risk],
                name="RiskAnalyserAgent",
                instructions="""You are a Risk Analyser Agent evaluating financial transactions for potential fraud.
Given a normalized transaction and customer profile, your task is to:
- Apply fraud detection logic using rule-based checks and regulatory compliance data
- Search the knowledge base for relevant regulations and compliance policies
- Assign a fraud risk score from 0 to 100
- Generate human-readable reasoning behind the score

When analyzing transactions:
1. First, search for relevant fraud detection regulations and compliance requirements
2. Use analyze_transaction_risk to calculate risk scores based on transaction factors
3. Reference specific regulations from the knowledge base in your analysis

Consider risk factors like high-risk countries, high amounts, suspicious account age, and device trust scores.""",
                id="risk-analyser-agent",
            )
            
            thread = agent.get_new_thread()
            
            for query in queries:
                print(f"\n{'='*80}")
                print(f"User: {query}")
                print(f"{agent.name or 'RiskAnalyserAgent'}: ", end="")
                async for update in agent.run_stream(
                    query,
                    thread=thread,
                ):
                    if update.text:
                        print(update.text, end="")
                print()  # New line after response


if __name__ == "__main__":
    asyncio.run(main())
