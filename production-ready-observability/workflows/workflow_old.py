"""
Fraud Detection Workflow Orchestration with Observability

This module orchestrates three fraud detection agents that are already registered
in the Azure AI Foundry portal:
1. CustomerDataAgent - registered via agents/customer_data_agent.py
2. RiskAnalyserAgent - registered via agents/risk_analyser_agent.py
3. FraudAlertAgent   - registered via agents/fraud_alert_agent.py

The workflow fetches agents from the portal by name, then interacts with them
via the Agents API (threads/messages/runs). Tool function implementations are
still provided locally so the hosted agents can execute function calls.
"""

import asyncio
import os
import re
import logging
import uuid
from typing import Never, Optional
from datetime import datetime, timedelta

import dotenv
from pydantic import BaseModel

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowOutputEvent,
    WorkflowStatusEvent,
    WorkflowRunState,
    handler,
)
from azure.ai.projects.aio import AIProjectClient
from azure.ai.agents.models import FunctionTool, ToolSet
from azure.identity.aio import DefaultAzureCredential

# Import tool implementations from existing agents (agents/ folder).
# These are needed so the hosted agents can execute function calls locally.
import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from agents.customer_data_agent import (
    get_customer_data,
    get_customer_transactions,
)
from agents.risk_analyser_agent import (
    analyze_transaction_risk,
)
from agents.fraud_alert_agent import (
    create_fraud_alert,
    get_fraud_alert,
)

from telemetry import (
    initialize_telemetry,
    get_telemetry_manager,
    send_business_event,
    get_current_trace_id,
)

# Load environment variables
dotenv.load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize telemetry
telemetry = get_telemetry_manager()

# Agent names as registered in the portal
CUSTOMER_DATA_AGENT_NAME = "CustomerDataAgent"
RISK_ANALYSER_AGENT_NAME = "RiskAnalyserAgent"
FRAUD_ALERT_AGENT_NAME = "FraudAlertAgent"


# ============================================================================
# Request/Response Models for Workflow
# ============================================================================

class AnalysisRequest(BaseModel):
    """Initial request to start the fraud detection workflow."""
    transaction_id: str
    customer_id: str
    amount: Optional[float] = None  # Transaction amount for metrics
    currency: Optional[str] = "USD"  # Currency code


class CustomerDataResponse(BaseModel):
    """Response from the CustomerDataAgent."""
    customer_id: str
    transaction_id: str
    analysis: str
    status: str
    amount: Optional[float] = None
    currency: Optional[str] = "USD"


class RiskAnalysisResponse(BaseModel):
    """Response from the RiskAnalyserAgent."""
    transaction_id: str
    customer_id: str
    risk_analysis: str
    risk_score: int
    risk_level: str
    recommendation: str
    status: str
    amount: Optional[float] = None
    currency: Optional[str] = "USD"
    model_confidence: Optional[float] = None  # Model confidence score


class FraudAlertResponse(BaseModel):
    """Response from the FraudAlertAgent."""
    transaction_id: str
    customer_id: str
    alert_response: str
    alert_created: bool
    workflow_status: str


# ============================================================================
# Shared Foundry Project Client
# ============================================================================

_project_client: AIProjectClient | None = None
_credential: DefaultAzureCredential | None = None
# Cache: agent_name -> agent_id
_agent_id_cache: dict[str, str] = {}


async def get_project_client() -> AIProjectClient:
    """Get or create the shared AIProjectClient."""
    global _project_client, _credential
    if _project_client is None:
        _credential = DefaultAzureCredential()
        _project_client = AIProjectClient(
            endpoint=os.environ["AI_FOUNDRY_PROJECT_ENDPOINT"],
            credential=_credential,
        )
    return _project_client


async def get_agent_id_by_name(agent_name: str) -> str:
    """Look up a portal-registered agent by name. Caches the result."""
    if agent_name in _agent_id_cache:
        return _agent_id_cache[agent_name]

    client = await get_project_client()
    async for agent in client.agents.list_agents():
        if agent.name == agent_name:
            _agent_id_cache[agent_name] = agent.id
            logger.info(f"Found portal agent '{agent_name}' → {agent.id}")
            return agent.id

    raise RuntimeError(
        f"Agent '{agent_name}' not found in the portal. "
        f"Run agents/{agent_name.lower()}.py first to register it."
    )


async def run_portal_agent(agent_name: str, toolset: ToolSet, user_message: str) -> str:
    """
    Send a message to a portal-registered agent and return its text response.
    Handles function-call tool execution via the supplied toolset.
    """
    client = await get_project_client()
    agent_id = await get_agent_id_by_name(agent_name)

    # Create a fresh thread for this invocation
    thread = await client.agents.threads.create()

    # Post the user message
    await client.agents.messages.create(
        thread_id=thread.id,
        role="user",
        content=user_message,
    )

    # Run the agent — create_and_process automatically handles function
    # calls by executing the local tool implementations in the toolset.
    run = await client.agents.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent_id,
        toolset=toolset,
    )

    if run.status == "failed":
        raise RuntimeError(f"Agent run failed: {run.last_error}")

    # Retrieve the assistant's response
    last_msg = await client.agents.messages.get_last_message_text_by_role(thread_id=thread.id, role="assistant")
    return last_msg if last_msg else "No response from agent"


# ============================================================================
# Tool Sets — map portal function definitions to local implementations
# ============================================================================

def _customer_data_toolset() -> ToolSet:
    ts = ToolSet()
    ts.add(FunctionTool(functions=[get_customer_data, get_customer_transactions]))
    return ts


def _risk_analyser_toolset() -> ToolSet:
    ts = ToolSet()
    ts.add(FunctionTool(functions=[analyze_transaction_risk]))
    return ts


def _fraud_alert_toolset() -> ToolSet:
    ts = ToolSet()
    ts.add(FunctionTool(functions=[create_fraud_alert, get_fraud_alert]))
    return ts


# ============================================================================
# Workflow Executors — each one calls a portal-hosted agent
# ============================================================================

class CustomerDataAgentExecutor(Executor):
    """Calls the CustomerDataAgent registered in the Foundry portal."""

    def __init__(self, id: str = "CustomerDataAgent"):
        super().__init__(id=id)

    @handler
    async def handle(
        self,
        request: AnalysisRequest,
        ctx: WorkflowContext[CustomerDataResponse],
    ) -> None:
        with telemetry.create_agent_span(
            "CustomerDataAgent",
            "data_retrieval",
            transaction_id=request.transaction_id,
            customer_id=request.customer_id,
        ) as span:
            span.add_event("Calling portal-hosted CustomerDataAgent")

            send_business_event("fraud_detection.customer_data.started", {
                "transaction_id": request.transaction_id,
                "customer_id": request.customer_id,
            })

            try:
                prompt = (
                    f"Analyze customer {request.customer_id} and their transactions "
                    f"comprehensively for fraud detection purposes."
                )

                start_time = asyncio.get_event_loop().time()
                analysis = await run_portal_agent(
                    CUSTOMER_DATA_AGENT_NAME,
                    _customer_data_toolset(),
                    prompt,
                )
                processing_time = asyncio.get_event_loop().time() - start_time

                span.set_attribute("ai.processing_time", processing_time)
                span.add_event("Customer data analysis completed")
                telemetry.record_transaction_processed("customer_data", request.transaction_id)

                send_business_event("fraud_detection.customer_data.completed", {
                    "transaction_id": request.transaction_id,
                    "customer_id": request.customer_id,
                    "processing_time": processing_time,
                })

                await ctx.send_message(CustomerDataResponse(
                    customer_id=request.customer_id,
                    transaction_id=request.transaction_id,
                    analysis=analysis,
                    status="SUCCESS",
                    amount=request.amount,
                    currency=request.currency,
                ))

            except Exception as e:
                span.record_exception(e)
                logger.error(f"CustomerDataAgent error: {e}")
                await ctx.send_message(CustomerDataResponse(
                    customer_id=request.customer_id,
                    transaction_id=request.transaction_id,
                    analysis=f"Error: {str(e)}",
                    status="ERROR",
                ))


class RiskAnalyserAgentExecutor(Executor):
    """Calls the RiskAnalyserAgent registered in the Foundry portal."""

    def __init__(self, id: str = "RiskAnalyserAgent"):
        super().__init__(id=id)

    @handler
    async def handle(
        self,
        customer_response: CustomerDataResponse,
        ctx: WorkflowContext[RiskAnalysisResponse],
    ) -> None:
        with telemetry.create_agent_span(
            "RiskAnalyserAgent",
            "risk_analysis",
            transaction_id=customer_response.transaction_id,
            customer_id=customer_response.customer_id,
        ) as span:
            span.add_event("Calling portal-hosted RiskAnalyserAgent")

            send_business_event("fraud_detection.risk_analysis.started", {
                "transaction_id": customer_response.transaction_id,
                "customer_id": customer_response.customer_id,
            })

            try:
                prompt = (
                    f"Based on this customer data analysis, perform a comprehensive "
                    f"risk assessment:\n\n{customer_response.analysis}\n\n"
                    f"Transaction ID: {customer_response.transaction_id}\n"
                    f"Customer ID: {customer_response.customer_id}\n\n"
                    f"Use the analyze_transaction_risk tool with appropriate parameters "
                    f"to calculate the risk score. Provide a complete risk assessment "
                    f"with score, level, and recommendation."
                )

                start_time = asyncio.get_event_loop().time()
                risk_analysis = await run_portal_agent(
                    RISK_ANALYSER_AGENT_NAME,
                    _risk_analyser_toolset(),
                    prompt,
                )
                processing_time = asyncio.get_event_loop().time() - start_time

                span.set_attribute("ai.processing_time", processing_time)

                # Parse risk score from the agent's response
                risk_score = 50
                match = re.search(r"risk\s*score[:\s]*(\d+)", risk_analysis.lower())
                if match:
                    risk_score = min(100, int(match.group(1)))

                risk_level = "HIGH" if risk_score >= 75 else ("MEDIUM" if risk_score >= 40 else "LOW")
                recommendation = "BLOCK" if risk_level == "HIGH" else ("INVESTIGATE" if risk_level == "MEDIUM" else "ALLOW")

                span.set_attributes({
                    "risk.score": risk_score,
                    "risk.level": risk_level,
                    "risk.recommendation": recommendation,
                })

                telemetry.record_risk_score(risk_score, customer_response.transaction_id, recommendation)

                # Metric 7: Model Confidence Tracking
                # Calculate confidence based on how decisive the risk score is
                # Scores near 0 or 100 indicate high confidence, scores near 50 indicate low confidence
                confidence_score = abs(risk_score - 50) / 50  # 0.0 to 1.0
                top_features = []
                if "amount" in risk_analysis.lower() or "transaction" in risk_analysis.lower():
                    top_features.append("transaction_amount")
                if "country" in risk_analysis.lower() or "location" in risk_analysis.lower():
                    top_features.append("geo_location")
                if "device" in risk_analysis.lower() or "pattern" in risk_analysis.lower():
                    top_features.append("behavior_pattern")
                if "velocity" in risk_analysis.lower() or "frequency" in risk_analysis.lower():
                    top_features.append("velocity_check")
                
                telemetry.record_model_prediction(
                    transaction_id=customer_response.transaction_id,
                    model_version="v2.3.1",
                    confidence_score=confidence_score,
                    prediction=risk_level,
                    top_features=top_features if top_features else ["general_risk_assessment"],
                )

                # Metric 3: Customer Friction - track when we're creating friction for customers
                if recommendation in ["BLOCK", "INVESTIGATE"]:
                    friction_type = "transaction_blocked" if recommendation == "BLOCK" else "step_up_auth"
                    telemetry.record_customer_friction(
                        customer_id=customer_response.customer_id,
                        transaction_id=customer_response.transaction_id,
                        friction_type=friction_type,
                        transaction_declined=(recommendation == "BLOCK"),
                    )

                send_business_event("fraud_detection.risk_analysis.completed", {
                    "transaction_id": customer_response.transaction_id,
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "recommendation": recommendation,
                })

                await ctx.send_message(RiskAnalysisResponse(
                    transaction_id=customer_response.transaction_id,
                    customer_id=customer_response.customer_id,
                    risk_analysis=risk_analysis,
                    risk_score=risk_score,
                    risk_level=risk_level,
                    recommendation=recommendation,
                    status="SUCCESS",
                    amount=customer_response.amount,
                    currency=customer_response.currency,
                    model_confidence=confidence_score,
                ))

            except Exception as e:
                span.record_exception(e)
                logger.error(f"RiskAnalyserAgent error: {e}")
                await ctx.send_message(RiskAnalysisResponse(
                    transaction_id=customer_response.transaction_id,
                    customer_id=customer_response.customer_id,
                    risk_analysis=f"Error: {str(e)}",
                    risk_score=0,
                    risk_level="UNKNOWN",
                    recommendation="INVESTIGATE",
                    status="ERROR",
                ))


class FraudAlertAgentExecutor(Executor):
    """Calls the FraudAlertAgent registered in the Foundry portal."""

    def __init__(self, id: str = "FraudAlertAgent"):
        super().__init__(id=id)

    @handler
    async def handle(
        self,
        risk_response: RiskAnalysisResponse,
        ctx: WorkflowContext[Never, FraudAlertResponse],
    ) -> None:
        with telemetry.create_agent_span(
            "FraudAlertAgent",
            "alert_creation",
            transaction_id=risk_response.transaction_id,
            customer_id=risk_response.customer_id,
        ) as span:
            span.add_event("Calling portal-hosted FraudAlertAgent")

            send_business_event("fraud_detection.fraud_alert.started", {
                "transaction_id": risk_response.transaction_id,
                "risk_score": risk_response.risk_score,
                "risk_level": risk_response.risk_level,
            })

            try:
                # Determine severity based on risk score
                if risk_response.risk_score >= 90:
                    severity = "CRITICAL"
                elif risk_response.risk_score >= 75:
                    severity = "HIGH"
                elif risk_response.risk_score >= 50:
                    severity = "MEDIUM"
                else:
                    severity = "LOW"

                prompt = (
                    f"Based on this risk analysis, determine if a fraud alert should "
                    f"be created:\n\n"
                    f"Risk Analysis:\n{risk_response.risk_analysis}\n\n"
                    f"Transaction ID: {risk_response.transaction_id}\n"
                    f"Customer ID: {risk_response.customer_id}\n"
                    f"Risk Score: {risk_response.risk_score}/100\n"
                    f"Risk Level: {risk_response.risk_level}\n"
                    f"Recommendation: {risk_response.recommendation}\n\n"
                    f"If the risk score is >= 40 or risk level is MEDIUM/HIGH, create "
                    f"a fraud alert using the create_fraud_alert tool with:\n"
                    f"- transaction_id: {risk_response.transaction_id}\n"
                    f"- customer_id: {risk_response.customer_id}\n"
                    f"- risk_score: {risk_response.risk_score}\n"
                    f"- severity: {severity}\n"
                    f"- status: OPEN\n"
                    f"- decision_action: {risk_response.recommendation}\n"
                    f"- reason: (provide a clear explanation based on the risk analysis)\n\n"
                    f"If risk is LOW and score < 40, explain why no alert is needed."
                )

                start_time = asyncio.get_event_loop().time()
                alert_response = await run_portal_agent(
                    FRAUD_ALERT_AGENT_NAME,
                    _fraud_alert_toolset(),
                    prompt,
                )
                processing_time = asyncio.get_event_loop().time() - start_time

                span.set_attribute("ai.processing_time", processing_time)

                alert_created = "alert created" in alert_response.lower() or "✅" in alert_response

                if alert_created:
                    telemetry.record_fraud_alert_created(
                        f"ALERT-{risk_response.transaction_id}",
                        severity,
                        risk_response.recommendation,
                        risk_response.transaction_id,
                    )
                    
                    # Metric 1: Fraud Loss Prevention - Track blocked amount when fraud is prevented
                    if risk_response.recommendation == "BLOCK" and risk_response.amount:
                        # Determine fraud type based on analysis content
                        fraud_type = "general_fraud"
                        if "account" in risk_response.risk_analysis.lower():
                            fraud_type = "account_takeover"
                        elif "card" in risk_response.risk_analysis.lower():
                            fraud_type = "card_fraud"
                        elif "identity" in risk_response.risk_analysis.lower():
                            fraud_type = "synthetic_identity"
                        
                        telemetry.record_fraud_prevented(
                            transaction_id=risk_response.transaction_id,
                            blocked_amount=risk_response.amount,
                            currency=risk_response.currency or "USD",
                            fraud_type=fraud_type,
                            risk_score=risk_response.risk_score,
                        )
                    
                    # Metric 9: Regulatory SAR Filing - File SAR for high-risk/high-amount transactions
                    # SAR thresholds: >$10,000 or CRITICAL severity
                    amount_threshold_exceeded = (risk_response.amount or 0) >= 10000
                    if severity in ["CRITICAL", "HIGH"] or amount_threshold_exceeded:
                        sar_id = f"SAR-{datetime.now().strftime('%Y')}-{uuid.uuid4().hex[:8].upper()}"
                        filing_deadline = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
                        
                        telemetry.record_sar_filed(
                            transaction_id=risk_response.transaction_id,
                            sar_id=sar_id,
                            filing_deadline=filing_deadline,
                            amount_threshold_exceeded=amount_threshold_exceeded,
                            customer_id=risk_response.customer_id,
                        )

                span.set_attributes({
                    "alert.created": alert_created,
                    "alert.severity": severity if alert_created else "NONE",
                })

                send_business_event("fraud_detection.fraud_alert.completed", {
                    "transaction_id": risk_response.transaction_id,
                    "alert_created": alert_created,
                    "severity": severity if alert_created else "NONE",
                })

                await ctx.yield_output(FraudAlertResponse(
                    transaction_id=risk_response.transaction_id,
                    customer_id=risk_response.customer_id,
                    alert_response=alert_response,
                    alert_created=alert_created,
                    workflow_status="SUCCESS",
                ))

            except Exception as e:
                span.record_exception(e)
                logger.error(f"FraudAlertAgent error: {e}")
                await ctx.yield_output(FraudAlertResponse(
                    transaction_id=risk_response.transaction_id,
                    customer_id=risk_response.customer_id,
                    alert_response=f"Error: {str(e)}",
                    alert_created=False,
                    workflow_status="ERROR",
                ))


# ============================================================================
# Workflow Runner
# ============================================================================

async def run_fraud_detection_workflow(
    transaction_id: str, 
    customer_id: str,
    amount: Optional[float] = None,
    currency: Optional[str] = "USD"
) -> FraudAlertResponse:
    """
    Execute the fraud detection workflow using the existing agents.
    
    Workflow: CustomerDataAgent → RiskAnalyserAgent → FraudAlertAgent
    
    Each executor uses the tools imported from the respective agent files.
    
    Args:
        transaction_id: The transaction ID to analyze
        customer_id: The customer ID associated with the transaction
        amount: Transaction amount for fraud prevention metrics (optional)
        currency: Currency code (default: USD)
    """
    
    with telemetry.create_workflow_span(
        "fraud_detection_workflow",
        business_process="financial_compliance",
        transaction_id=transaction_id,
        customer_id=customer_id
    ) as workflow_span:
        
        workflow_span.add_event("Building workflow with portal-hosted agents")
        
        # Build the sequential workflow
        workflow = (
            WorkflowBuilder()
            .register_executor(lambda: CustomerDataAgentExecutor(), name="CustomerDataAgent")
            .register_executor(lambda: RiskAnalyserAgentExecutor(), name="RiskAnalyserAgent")
            .register_executor(lambda: FraudAlertAgentExecutor(), name="FraudAlertAgent")
            .add_edge("CustomerDataAgent", "RiskAnalyserAgent")
            .add_edge("RiskAnalyserAgent", "FraudAlertAgent")
            .set_start_executor("CustomerDataAgent")
            .build()
        )
        
        request = AnalysisRequest(
            transaction_id=transaction_id,
            customer_id=customer_id,
            amount=amount,
            currency=currency,
        )
        
        workflow_span.set_attributes({
            "workflow.executors": 3,
            "workflow.type": "sequential",
            "workflow.uses_portal_agents": True
        })
        
        workflow_span.add_event("Starting workflow execution")
        
        final_result = None
        
        async for event in workflow.run_stream(request):
            if isinstance(event, WorkflowStatusEvent):
                workflow_span.add_event(f"Workflow status: {event.state}")
                if event.state == WorkflowRunState.IDLE:
                    print("✓ Workflow completed")
            elif isinstance(event, WorkflowOutputEvent):
                final_result = event.data
        
        return final_result


async def main():
    """Main function to run the fraud detection workflow using portal-hosted agents."""
    
    # Initialize observability
    initialize_telemetry()
    
    with telemetry.create_workflow_span("fraud_detection_application") as main_span:
        trace_id = get_current_trace_id()
        print(f"\n🔍 Fraud Detection Workflow (Portal-Hosted Agents)")
        print(f"📊 Trace ID: {trace_id}")
        print("=" * 70)
        
        main_span.set_attributes({
            "application.name": "fraud_detection_system",
            "application.version": "1.0.0",
            "uses_portal_agents": True
        })
        
        # Test transactions with amounts for metrics tracking
        test_cases = [
            ("TX1001", "CUST1001", 5200.00, "USD"),   # Standard transaction
            ("TX1005", "CUST1005", 15000.00, "USD"),  # High-value transaction (triggers SAR)
        ]
        
        for transaction_id, customer_id, amount, currency in test_cases:
            print(f"\n{'='*70}")
            print(f"Processing: Transaction {transaction_id}, Customer {customer_id}")
            print(f"Amount: {amount} {currency}")
            print(f"{'='*70}")
            
            try:
                result = await run_fraud_detection_workflow(
                    transaction_id, 
                    customer_id,
                    amount=amount,
                    currency=currency,
                )
                
                if result:
                    print(f"\n📋 WORKFLOW RESULT:")
                    print(f"   Transaction: {result.transaction_id}")
                    print(f"   Customer: {result.customer_id}")
                    print(f"   Alert Created: {'✅ YES' if result.alert_created else '❌ NO'}")
                    print(f"   Status: {result.workflow_status}")
                    print(f"\n   Agent Response:")
                    print(f"   {result.alert_response[:500]}...")
                else:
                    print("❌ No result")
                    
            except Exception as e:
                print(f"❌ Error: {str(e)}")
                main_span.record_exception(e)
        
        print(f"\n{'='*70}")
        print(f"🔍 Trace completed: {trace_id}")
    
    # Clean up the shared project client
    global _project_client, _credential
    if _project_client:
        await _project_client.close()
        _project_client = None
    if _credential:
        await _credential.close()
        _credential = None


if __name__ == "__main__":
    asyncio.run(main())
