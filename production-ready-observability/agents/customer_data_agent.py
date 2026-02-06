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
Customer Data Agent with Foundry Tracing
This agent retrieves and enriches customer data from Cosmos DB with full observability.
"""

# For loading environment variables
dotenv.load_dotenv()

logger = logging.getLogger(__name__)

# Configuration
cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT")
cosmos_key = os.environ.get("COSMOS_KEY")

# Initialize Cosmos DB clients globally for function tools (conditional)
customers_container = None
transactions_container = None
if cosmos_endpoint and cosmos_key:
    try:
        cosmos_client = CosmosClient(cosmos_endpoint, cosmos_key)
        database = cosmos_client.get_database_client("FinancialComplianceDB")
        customers_container = database.get_container_client("Customers")
        transactions_container = database.get_container_client("Transactions")
        logger.info("Cosmos DB connected successfully")
    except Exception as e:
        logger.warning(f"Could not connect to Cosmos DB: {e}. Using mock data.")
else:
    logger.warning("Cosmos DB credentials not found. Using mock data. Set COSMOS_ENDPOINT and COSMOS_KEY in .env file.")


async def get_customer_data(
    customer_id: Annotated[str, Field(description="The customer ID to fetch data for.")],
) -> str:
    """Get customer data from Cosmos DB including profile, account age, country, and device info."""
    if not customers_container:
        return f"Cosmos DB not configured. Cannot fetch customer data. Please set COSMOS_ENDPOINT and COSMOS_KEY."
    try:
        query = f"SELECT * FROM c WHERE c.customer_id = '{customer_id}'"
        items = list(customers_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        if items:
            customer = items[0]
            return f"Customer {customer_id}: Name={customer.get('name', 'N/A')}, Country={customer.get('country', 'N/A')}, Account Age={customer.get('account_age_days', 'N/A')} days, Risk Level={customer.get('risk_level', 'N/A')}"
        else:
            return f"Customer {customer_id} not found"
    except Exception as e:
        logger.error(f"Error fetching customer data: {e}")
        return f"Error fetching customer {customer_id}: {str(e)}"


async def get_customer_transactions(
    customer_id: Annotated[str, Field(description="The customer ID to fetch transactions for.")],
) -> str:
    """Get all transactions for a customer from Cosmos DB with normalized fields."""
    if not transactions_container:
        return f"Cosmos DB not configured. Cannot fetch transaction data. Please set COSMOS_ENDPOINT and COSMOS_KEY."
    try:
        query = f"SELECT * FROM c WHERE c.customer_id = '{customer_id}'"
        items = list(transactions_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        if not items:
            return f"No transactions found for customer {customer_id}"
        
        # Normalize and summarize transactions
        summary = f"Found {len(items)} transactions for {customer_id}:\n"
        for i, txn in enumerate(items[:5], 1):  # Show first 5
            summary += f"{i}. Amount: ${txn.get('amount', 'N/A')}, Type: {txn.get('transaction_type', 'N/A')}, Date: {txn.get('timestamp', 'N/A')}, Status: {txn.get('status', 'N/A')}\n"
        
        if len(items) > 5:
            summary += f"... and {len(items) - 5} more transactions"
        
        return summary
    except Exception as e:
        logger.error(f"Error fetching transactions: {e}")
        return f"Error fetching transactions for {customer_id}: {str(e)}"


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
        # This will enable tracing and configure the application to send telemetry data to the
        # Application Insights instance attached to the Azure AI project.
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
        print("Observability is set up. Starting Customer Data Agent...")

        # Register agent in Azure AI Foundry portal for enterprise observability
        print("\n📝 Registering agent in Azure AI Foundry portal...")
        try:
            # Use the sync client for agent registration
            from azure.ai.projects import AIProjectClient as SyncAIProjectClient
            from azure.ai.projects.models import PromptAgentDefinition, FunctionTool
            from azure.identity import DefaultAzureCredential
            
            sync_client = SyncAIProjectClient(
                endpoint=os.environ["AI_FOUNDRY_PROJECT_ENDPOINT"],
                subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
                resource_group_name=os.environ["AZURE_RESOURCE_GROUP_NAME"],
                project_name=os.environ["AI_FOUNDRY_PROJECT_NAME"],
                credential=DefaultAzureCredential()
            )
            
            agent_id = "customer-data-agent"
            try:
                # Check if agent already exists
                registered_agent = sync_client.agents.get(agent_id)
                print(f"✅ Agent already registered in portal: {registered_agent.id}")
                print(f"   Name: {registered_agent.name}")
            except:
                # Agent doesn't exist, create it
                definition = PromptAgentDefinition(
                    model=os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4"),
                    instructions="""You are a Data Ingestion Agent responsible for preparing structured input for fraud detection. 
You will receive raw transaction records and customer profiles. Your task is to:
- Normalize fields (e.g., currency, timestamps, amounts)
- Remove or flag incomplete data
- Enrich each transaction with relevant customer metadata (e.g., account age, country, device info)
- Output a clean JSON object per transaction with unified structure

Use the available functions to fetch customer data and transactions.
Ensure the format is consistent and ready for analysis.""",
                    tools=[
                        FunctionTool(
                            name="get_customer_data",
                            description="Get customer data from Cosmos DB including profile, account age, country, and device info.",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "customer_id": {
                                        "type": "string",
                                        "description": "The customer ID to fetch data for."
                                    }
                                },
                                "required": ["customer_id"]
                            }
                        ),
                        FunctionTool(
                            name="get_customer_transactions",
                            description="Get all transactions for a customer from Cosmos DB with normalized fields.",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "customer_id": {
                                        "type": "string",
                                        "description": "The customer ID to fetch transactions for."
                                    }
                                },
                                "required": ["customer_id"]
                            }
                        )
                    ]
                )
                
                registered_agent = sync_client.agents.create(
                    name="CustomerDataAgent",
                    definition=definition,
                    description="Data Ingestion Agent for fraud detection with Cosmos DB integration",
                    metadata={"version": "1.0", "framework": "agent-framework", "observability": "enabled"}
                )
                print(f"✅ Agent registered in portal: {registered_agent.id}")
                print(f"   Name: {registered_agent.name}")
                print(f"   View in Azure AI Foundry: https://ai.azure.com")
            
            sync_client.close()
        except Exception as e:
            print(f"⚠️  Could not register agent in portal: {e}")
            print("   Agent will run locally with telemetry only.")

        # Test queries for the customer data agent
        queries = [
            "Analyze customer CUST1005 comprehensively.",
            "Get the transaction history for CUST1002 and identify any patterns.",
            "Compare the risk profiles of CUST1001 and CUST1003."
        ]

        with get_tracer().start_as_current_span("Customer Data Agent Chat", kind=SpanKind.CLIENT) as current_span:
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

            agent = ChatAgent(
                chat_client=OpenAIChatClient(
                    async_client=azure_openai_client,
                    model_id=os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4"),
                ),
                tools=[get_customer_data, get_customer_transactions],
                name="CustomerDataAgent",
                instructions="""You are a Data Ingestion Agent responsible for preparing structured input for fraud detection. 
                You will receive raw transaction records and customer profiles. Your task is to:
                - Normalize fields (e.g., currency, timestamps, amounts)
                - Remove or flag incomplete data
                - Enrich each transaction with relevant customer metadata (e.g., account age, country, device info)
                - Output a clean JSON object per transaction with unified structure
                
                Use the available functions to fetch customer data and transactions.
                Ensure the format is consistent and ready for analysis.""",
                id="customer-data-agent",
            )
            
            thread = agent.get_new_thread()
            
            for query in queries:
                print(f"\n{'='*80}")
                print(f"User: {query}")
                print(f"{agent.name or 'CustomerDataAgent'}: ", end="")
                async for update in agent.run_stream(
                    query,
                    thread=thread,
                ):
                    if update.text:
                        print(update.text, end="")
                print()  # New line after response


if __name__ == "__main__":
    asyncio.run(main())
