# Copyright (c) Microsoft. All rights reserved.

import asyncio
import json
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
Fraud Alert Agent with Foundry Tracing
This agent creates and manages fraud alerts for suspicious financial transactions.
"""

# For loading environment variables
dotenv.load_dotenv()

logger = logging.getLogger(__name__)

# Configuration
cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT")
cosmos_key = os.environ.get("COSMOS_KEY")

# Initialize Cosmos DB clients (conditional on credentials being available)
alerts_container = None
if cosmos_endpoint and cosmos_key:
    try:
        cosmos_client = CosmosClient(cosmos_endpoint, cosmos_key)
        database = cosmos_client.get_database_client("FinancialComplianceDB")
        alerts_container = database.get_container_client("FraudAlerts")
        logger.info("Cosmos DB connected successfully")
    except Exception as e:
        logger.warning(f"Could not connect to Cosmos DB: {e}. Alerts will be stored in memory only.")
        alerts_container = None
else:
    logger.warning("Cosmos DB credentials not found. Alerts will be stored in memory only. Set COSMOS_ENDPOINT and COSMOS_KEY in .env file.")

# Fraud alert enumerations
SEVERITY_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
STATUS_VALUES = ["OPEN", "INVESTIGATING", "RESOLVED", "FALSE_POSITIVE"]
DECISION_ACTIONS = ["ALLOW", "BLOCK", "MONITOR", "INVESTIGATE"]


async def create_fraud_alert(
    transaction_id: Annotated[str, Field(description="The transaction ID for the alert.")],
    customer_id: Annotated[str, Field(description="The customer ID associated with the transaction.")],
    risk_score: Annotated[int, Field(description="Risk score from 0 to 100.")],
    severity: Annotated[str, Field(description="Alert severity: LOW, MEDIUM, HIGH, or CRITICAL.")],
    status: Annotated[str, Field(description="Alert status: OPEN, INVESTIGATING, RESOLVED, or FALSE_POSITIVE.")],
    decision_action: Annotated[str, Field(description="Decision action: ALLOW, BLOCK, MONITOR, or INVESTIGATE.")],
    reason: Annotated[str, Field(description="Detailed reason for the alert.")],
) -> str:
    """Create a fraud alert for a suspicious transaction with specified severity, status, and decision action."""
    try:
        # Validate enumerations
        if severity not in SEVERITY_LEVELS:
            return f"Invalid severity: {severity}. Must be one of {SEVERITY_LEVELS}"
        if status not in STATUS_VALUES:
            return f"Invalid status: {status}. Must be one of {STATUS_VALUES}"
        if decision_action not in DECISION_ACTIONS:
            return f"Invalid decision_action: {decision_action}. Must be one of {DECISION_ACTIONS}"
        
        # Create alert document
        alert = {
            "id": f"ALERT-{transaction_id}",
            "transaction_id": transaction_id,
            "customer_id": customer_id,
            "risk_score": risk_score,
            "severity": severity,
            "status": status,
            "decision_action": decision_action,
            "reason": reason,
            "created_at": dotenv.datetime.now().isoformat() if hasattr(dotenv, 'datetime') else "2024-01-01T00:00:00"
        }
        
        # Store in Cosmos DB if available
        if alerts_container:
            try:
                alerts_container.upsert_item(alert)
                logger.info(f"Created fraud alert {alert['id']} in Cosmos DB")
            except Exception as e:
                logger.error(f"Failed to store alert in Cosmos DB: {e}")
        
        result = f"✅ Fraud Alert Created:\n"
        result += f"Alert ID: {alert['id']}\n"
        result += f"Transaction: {transaction_id}\n"
        result += f"Customer: {customer_id}\n"
        result += f"Risk Score: {risk_score}/100\n"
        result += f"Severity: {severity}\n"
        result += f"Status: {status}\n"
        result += f"Decision: {decision_action}\n"
        result += f"Reason: {reason}\n"
        
        return result
    except Exception as e:
        logger.error(f"Error creating fraud alert: {e}")
        return f"Error creating fraud alert: {str(e)}"


async def get_fraud_alert(
    alert_id: Annotated[str, Field(description="The alert ID to retrieve.")],
) -> str:
    """Retrieve details of an existing fraud alert by alert ID."""
    try:
        if not alerts_container:
            return "Fraud alerts storage not configured."
        
        query = f"SELECT * FROM c WHERE c.id = '{alert_id}'"
        items = list(alerts_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        if items:
            alert = items[0]
            result = f"Fraud Alert Details:\n"
            result += f"Alert ID: {alert['id']}\n"
            result += f"Transaction: {alert['transaction_id']}\n"
            result += f"Customer: {alert['customer_id']}\n"
            result += f"Risk Score: {alert['risk_score']}/100\n"
            result += f"Severity: {alert['severity']}\n"
            result += f"Status: {alert['status']}\n"
            result += f"Decision: {alert['decision_action']}\n"
            result += f"Reason: {alert['reason']}\n"
            result += f"Created: {alert.get('created_at', 'N/A')}\n"
            return result
        else:
            return f"No alert found with ID: {alert_id}"
    except Exception as e:
        logger.error(f"Error retrieving fraud alert: {e}")
        return f"Error retrieving alert {alert_id}: {str(e)}"


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
        print("Observability is set up. Starting Fraud Alert Agent...")

        # Register agent in Azure AI Foundry portal
        print("\n📝 Registering agent in Azure AI Foundry portal...")
        try:
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
            
            definition = PromptAgentDefinition(
                    model=os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4"),
                    instructions="""You are a Fraud Alert Management Agent that specializes in creating and managing fraud alerts for financial transactions.

Your responsibilities include:
- Analyzing risk assessment results to determine if fraud alerts are needed
- Creating appropriate fraud alerts with correct severity and status
- Determining proper decision actions (ALLOW, BLOCK, MONITOR, INVESTIGATE)
- Providing clear reasoning for alert decisions

When creating fraud alerts, use these enumerations:
- severity (LOW, MEDIUM, HIGH, CRITICAL)
- status (OPEN, INVESTIGATING, RESOLVED, FALSE_POSITIVE)
- decision action (ALLOW, BLOCK, MONITOR, INVESTIGATE)

Create fraud alerts for transactions that meet any of these criteria:
1. High risk scores (>= 75)
2. Sanctions-related concerns
3. High-risk jurisdictions
4. Suspicious patterns or anomalies
5. Regulatory compliance violations

Always create comprehensive alerts with proper risk factor documentation and clear reasoning.""",
                    tools=[
                        FunctionTool(
                            name="create_fraud_alert",
                            description="Create a fraud alert for a suspicious transaction with specified severity, status, and decision action.",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "transaction_id": {"type": "string", "description": "The transaction ID for the alert."},
                                    "customer_id": {"type": "string", "description": "The customer ID associated with the transaction."},
                                    "risk_score": {"type": "integer", "description": "Risk score from 0 to 100."},
                                    "severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"], "description": "Alert severity."},
                                    "status": {"type": "string", "enum": ["OPEN", "INVESTIGATING", "RESOLVED", "FALSE_POSITIVE"], "description": "Alert status."},
                                    "decision_action": {"type": "string", "enum": ["ALLOW", "BLOCK", "MONITOR", "INVESTIGATE"], "description": "Decision action."},
                                    "reason": {"type": "string", "description": "Detailed reason for the alert."}
                                },
                                "required": ["transaction_id", "customer_id", "risk_score", "severity", "status", "decision_action", "reason"]
                            }
                        ),
                        FunctionTool(
                            name="get_fraud_alert",
                            description="Retrieve details of an existing fraud alert by alert ID.",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "alert_id": {"type": "string", "description": "The alert ID to retrieve."}
                                },
                                "required": ["alert_id"]
                            }
                        )
                    ]
                )
            
            registered_agent = sync_client.agents.create(
                name="FraudAlertAgent",
                definition=definition,
                description="Fraud alert management agent for creating and tracking fraud alerts",
                metadata={"version": "1.0", "framework": "agent-framework", "observability": "enabled"}
            )
            print(f"✅ Agent registered in portal: {registered_agent.id}")
            print(f"   Name: {registered_agent.name}")
            print(f"   View in Azure AI Foundry: https://ai.azure.com")
            
            sync_client.close()
        except Exception as e:
            print(f"⚠️  Could not register agent in portal: {e}")
            print("   Agent will run locally with telemetry only.")

        # Test queries
        queries = [
            "Create a fraud alert for transaction TXN001, customer CUST1001, with risk score 85, severity HIGH, status OPEN, decision action BLOCK, and reason 'High-risk transaction from sanctioned country'",
            "Retrieve fraud alert ALERT-TXN001",
        ]

        with get_tracer().start_as_current_span("Fraud Alert Agent Chat", kind=SpanKind.CLIENT) as current_span:
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
                tools=[create_fraud_alert, get_fraud_alert],
                name="FraudAlertAgent",
                instructions="""You are a Fraud Alert Management Agent that specializes in creating and managing fraud alerts for financial transactions.

Your responsibilities include:
- Analyzing risk assessment results to determine if fraud alerts are needed
- Creating appropriate fraud alerts with correct severity and status
- Determining proper decision actions (ALLOW, BLOCK, MONITOR, INVESTIGATE)
- Providing clear reasoning for alert decisions

When creating fraud alerts, use these enumerations:
- severity (LOW, MEDIUM, HIGH, CRITICAL)
- status (OPEN, INVESTIGATING, RESOLVED, FALSE_POSITIVE)
- decision action (ALLOW, BLOCK, MONITOR, INVESTIGATE)

Create fraud alerts for transactions that meet any of these criteria:
1. High risk scores (>= 75)
2. Sanctions-related concerns
3. High-risk jurisdictions
4. Suspicious patterns or anomalies
5. Regulatory compliance violations

Always create comprehensive alerts with proper risk factor documentation and clear reasoning.""",
                id="fraud-alert-agent",
            )
            
            thread = agent.get_new_thread()
            
            for query in queries:
                print(f"\n{'='*80}")
                print(f"User: {query}")
                print(f"{agent.name or 'FraudAlertAgent'}: ", end="")
                async for update in agent.run_stream(
                    query,
                    thread=thread,
                ):
                    if update.text:
                        print(update.text, end="")
                print()  # New line after response


if __name__ == "__main__":
    asyncio.run(main())
