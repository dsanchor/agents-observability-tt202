"""
Telemetry and Observability Module for Fraud Detection Workflow

This module provides comprehensive observability capabilities including:
- OpenTelemetry tracing and metrics
- Azure Application Insights integration
- Custom business events and metrics
- Cosmos DB operation instrumentation

Based on the azure-trust-agents challenge-3 patterns, adapted for the fraud-agents workflow.
"""

import os
from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Import Azure Monitor for Application Insights
from azure.monitor.opentelemetry import configure_azure_monitor

# Import observability components from Agent Framework
from agent_framework.observability import (
    enable_instrumentation,
    get_tracer,
    get_meter,
    create_processing_span,
)
from opentelemetry.trace import SpanKind
from opentelemetry.trace.span import format_trace_id
from opentelemetry import trace, metrics

# Load environment variables
load_dotenv(override=True)


class TelemetryManager:
    """Central telemetry management class for the fraud detection workflow."""
    
    def __init__(self):
        self.tracer = None
        self.meter = None
        self._initialized = False
        
        # Metrics
        self.transaction_counter = None
        self.risk_score_histogram = None
        self.fraud_alert_counter = None
        
        # New business metrics
        self.amount_blocked_counter = None
        self.false_positive_counter = None
        self.customer_friction_counter = None
        self.model_confidence_histogram = None
        self.sar_filed_counter = None
    
    def initialize_observability(self):
        """Initialize observability with Azure Application Insights."""
        
        if self._initialized:
            return
        
        # Get configuration from environment variables
        app_insights_connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
        
        if app_insights_connection_string:
            # Configure Azure Monitor for Application Insights
            configure_azure_monitor(
                connection_string=app_insights_connection_string,
                enable_live_metrics=True,
            )
        
        # Enable agent framework instrumentation
        enable_instrumentation()
        
        # Initialize tracer and meter
        self.tracer = get_tracer("fraud_detection_workflow", "1.0.0")
        self.meter = get_meter("fraud_detection_metrics", "1.0.0")
        
        # Initialize custom metrics
        self._initialize_metrics()
        
        print("🔍 Observability initialized for fraud detection workflow")
        print(f"📊 Application Insights: {'✓' if app_insights_connection_string else '✗'}")
        
        self._initialized = True
    
    def _initialize_metrics(self):
        """Initialize custom metrics for business KPIs."""
        
        self.transaction_counter = self.meter.create_counter(
            name="fraud_detection.transactions.processed",
            description="Number of transactions processed",
            unit="1"
        )
        
        self.risk_score_histogram = self.meter.create_histogram(
            name="fraud_detection.risk_score.distribution",
            description="Distribution of risk scores",
            unit="1"
        )
        
        self.fraud_alert_counter = self.meter.create_counter(
            name="fraud_detection.alerts.created",
            description="Number of fraud alerts created by severity",
            unit="1"
        )
        
        # Metric 1: Fraud Loss Prevention
        self.amount_blocked_counter = self.meter.create_counter(
            name="fraud_detection.amount_blocked",
            description="Total monetary amount blocked due to fraud prevention",
            unit="USD"
        )
        
        # Metric 2: False Positive Tracking
        self.false_positive_counter = self.meter.create_counter(
            name="fraud_detection.false_positives",
            description="Number of false positive fraud detections",
            unit="1"
        )
        
        # Metric 3: Customer Friction Events
        self.customer_friction_counter = self.meter.create_counter(
            name="fraud_detection.customer_friction",
            description="Number of customer friction events triggered",
            unit="1"
        )
        
        # Metric 7: Model Confidence Tracking
        self.model_confidence_histogram = self.meter.create_histogram(
            name="fraud_detection.model.confidence",
            description="Distribution of model confidence scores",
            unit="1"
        )
        
        # Metric 9: Regulatory SAR Filings
        self.sar_filed_counter = self.meter.create_counter(
            name="fraud_detection.compliance.sar_filed",
            description="Number of Suspicious Activity Reports filed",
            unit="1"
        )
    
    def send_business_event(self, event_name: str, properties: Dict[str, Any]):
        """Send business event using OpenTelemetry for comprehensive tracing."""
        
        # Method 1: OpenTelemetry Event on current span
        current_span = trace.get_current_span()
        if current_span:
            current_span.add_event(f"business_event.{event_name}", properties)
        
        # Method 2: Create dedicated span for business event
        if self.tracer:
            with self.tracer.start_as_current_span(
                f"business_event.{event_name}",
                kind=SpanKind.INTERNAL,
                attributes={f"event.{k}": str(v) for k, v in properties.items()}
            ) as event_span:
                event_span.set_attribute("event.type", "business_metric")
                event_span.set_attribute("event.name", event_name)
        
        print(f"📊 Business event: {event_name}")
    
    def record_transaction_processed(self, step: str, transaction_id: str):
        """Record that a transaction was processed."""
        if self.transaction_counter:
            self.transaction_counter.add(1, {
                "step": step,
                "transaction_id": transaction_id
            })
    
    def record_risk_score(self, risk_score: float, transaction_id: str, recommendation: str):
        """Record risk score distribution."""
        if self.risk_score_histogram:
            self.risk_score_histogram.record(risk_score, {
                "transaction_id": transaction_id,
                "recommendation": recommendation
            })
    
    def record_fraud_alert_created(self, alert_id: str, severity: str, decision_action: str, transaction_id: str):
        """Record fraud alert creation."""
        if self.fraud_alert_counter:
            self.fraud_alert_counter.add(1, {
                "alert_id": alert_id,
                "severity": severity,
                "decision_action": decision_action,
                "transaction_id": transaction_id
            })
    
    # ========================================================================
    # New Business Metrics (1, 2, 3, 7, 9)
    # ========================================================================
    
    def record_fraud_prevented(self, transaction_id: str, blocked_amount: float, 
                                currency: str, fraud_type: str, risk_score: int):
        """
        Metric 1: Fraud Loss Prevention
        Record when a fraudulent transaction is blocked, tracking financial impact.
        """
        if self.amount_blocked_counter:
            self.amount_blocked_counter.add(blocked_amount, {
                "transaction_id": transaction_id,
                "currency": currency,
                "fraud_type": fraud_type,
            })
        
        self.send_business_event("fraud_detection.fraud.prevented", {
            "transaction_id": transaction_id,
            "blocked_amount": blocked_amount,
            "currency": currency,
            "fraud_type": fraud_type,
            "risk_score": risk_score,
        })
    
    def record_false_positive(self, transaction_id: str, original_decision: str,
                               customer_friction_score: int, resolution_time_hours: float,
                               compensation_amount: float = 0.0):
        """
        Metric 2: False Positive Cost Tracking
        Record false positives for model improvement and customer experience tracking.
        """
        if self.false_positive_counter:
            self.false_positive_counter.add(1, {
                "transaction_id": transaction_id,
                "original_decision": original_decision,
            })
        
        self.send_business_event("fraud_detection.false_positive.confirmed", {
            "transaction_id": transaction_id,
            "original_decision": original_decision,
            "customer_friction_score": customer_friction_score,
            "resolution_time_hours": resolution_time_hours,
            "compensation_amount": compensation_amount,
        })
    
    def record_customer_friction(self, customer_id: str, transaction_id: str,
                                  friction_type: str, transaction_declined: bool,
                                  customer_tenure_days: int = 0, 
                                  customer_lifetime_value: float = 0.0):
        """
        Metric 3: Customer Friction Events
        Track friction events that impact customer experience.
        """
        if self.customer_friction_counter:
            self.customer_friction_counter.add(1, {
                "friction_type": friction_type,
                "transaction_declined": str(transaction_declined),
            })
        
        self.send_business_event("fraud_detection.customer.friction", {
            "customer_id": customer_id,
            "transaction_id": transaction_id,
            "friction_type": friction_type,
            "transaction_declined": transaction_declined,
            "customer_tenure_days": customer_tenure_days,
            "customer_lifetime_value": customer_lifetime_value,
        })
    
    def record_model_prediction(self, transaction_id: str, model_version: str,
                                 confidence_score: float, prediction: str,
                                 top_features: list = None):
        """
        Metric 7: Model Confidence Tracking
        Track model predictions for ML observability and model improvement.
        """
        if self.model_confidence_histogram:
            self.model_confidence_histogram.record(confidence_score, {
                "model_version": model_version,
                "prediction": prediction,
            })
        
        self.send_business_event("fraud_detection.model.prediction", {
            "transaction_id": transaction_id,
            "model_version": model_version,
            "confidence_score": confidence_score,
            "prediction": prediction,
            "top_features": top_features or [],
        })
    
    def record_sar_filed(self, transaction_id: str, sar_id: str, 
                          filing_deadline: str, amount_threshold_exceeded: bool,
                          customer_id: str = None):
        """
        Metric 9: Regulatory Reporting Events
        Track Suspicious Activity Report (SAR) filings for compliance.
        """
        if self.sar_filed_counter:
            self.sar_filed_counter.add(1, {
                "amount_threshold_exceeded": str(amount_threshold_exceeded),
            })
        
        self.send_business_event("fraud_detection.compliance.sar_filed", {
            "transaction_id": transaction_id,
            "sar_id": sar_id,
            "filing_deadline": filing_deadline,
            "amount_threshold_exceeded": amount_threshold_exceeded,
            "customer_id": customer_id,
        })
    
    def create_cosmos_span(self, operation: str, collection: str, **attributes):
        """Create a span for Cosmos DB operations."""
        return self.tracer.start_as_current_span(
            f"cosmos_db.{collection.lower()}.{operation}",
            attributes={
                "db.operation": operation,
                "db.collection.name": collection,
                **attributes
            }
        )
    
    def create_processing_span(self, executor_id: str, executor_type: str, message_type: str):
        """Create a processing span for executors."""
        return create_processing_span(
            executor_id=executor_id,
            executor_type=executor_type,
            message_type=message_type
        )
    
    def create_workflow_span(self, workflow_name: str, **attributes):
        """Create a workflow span."""
        return self.tracer.start_as_current_span(
            workflow_name,
            kind=SpanKind.CLIENT,
            attributes={
                "workflow.name": workflow_name,
                "workflow.version": "1.0.0",
                **attributes
            }
        )
    
    def create_agent_span(self, agent_name: str, operation: str, **attributes):
        """Create a span for agent operations."""
        return self.tracer.start_as_current_span(
            f"agent.{agent_name}.{operation}",
            kind=SpanKind.CLIENT,
            attributes={
                "agent.name": agent_name,
                "agent.operation": operation,
                **attributes
            }
        )
    
    def get_current_trace_id(self) -> Optional[str]:
        """Get the current trace ID."""
        current_span = trace.get_current_span()
        if current_span:
            return format_trace_id(current_span.get_span_context().trace_id)
        return None


class CosmosDbInstrumentation:
    """Instrumentation wrapper for Cosmos DB operations."""
    
    def __init__(self, telemetry_manager: TelemetryManager):
        self.telemetry = telemetry_manager
    
    def instrument_query(self, func):
        """Decorator to instrument Cosmos DB query operations."""
        def wrapper(*args, **kwargs):
            operation_name = func.__name__
            with self.telemetry.create_cosmos_span("query", operation_name) as span:
                try:
                    span.add_event(f"Executing {operation_name}")
                    result = func(*args, **kwargs)
                    span.set_attribute("cosmos_db.success", True)
                    span.add_event(f"{operation_name} completed successfully")
                    return result
                except Exception as e:
                    span.set_attribute("cosmos_db.success", False)
                    span.set_attribute("cosmos_db.error", str(e))
                    span.record_exception(e)
                    raise
        return wrapper


# Global telemetry instance
telemetry_manager = TelemetryManager()


# Convenience functions for easy access
def initialize_telemetry():
    """Initialize the global telemetry manager."""
    telemetry_manager.initialize_observability()


def flush_telemetry():
    """Flush all pending telemetry data to ensure delivery."""
    from opentelemetry import trace as otel_trace, metrics as otel_metrics
    
    # Flush traces
    tracer_provider = otel_trace.get_tracer_provider()
    if hasattr(tracer_provider, 'force_flush'):
        tracer_provider.force_flush(timeout_millis=30000)
    
    # Flush metrics  
    meter_provider = otel_metrics.get_meter_provider()
    if hasattr(meter_provider, 'force_flush'):
        meter_provider.force_flush(timeout_millis=30000)
    
    print("📤 Telemetry data flushed to Application Insights")


def get_telemetry_manager() -> TelemetryManager:
    """Get the global telemetry manager instance."""
    return telemetry_manager


def send_business_event(event_name: str, properties: Dict[str, Any]):
    """Send a business event through the telemetry manager."""
    telemetry_manager.send_business_event(event_name, properties)


def get_current_trace_id() -> Optional[str]:
    """Get the current trace ID."""
    return telemetry_manager.get_current_trace_id()


# Export key functions and classes
__all__ = [
    'TelemetryManager',
    'CosmosDbInstrumentation',
    'telemetry_manager',
    'initialize_telemetry',
    'flush_telemetry',
    'get_telemetry_manager',
    'send_business_event',
    'get_current_trace_id'
]
