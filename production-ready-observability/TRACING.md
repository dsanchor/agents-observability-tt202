# How Tracing Works in This Workflow

This document explains the distributed tracing implementation in the fraud detection workflow, covering initialization, span creation, business events, and metrics.

## Core Components

### 1. Initialization

The telemetry system is initialized once at startup in `workflows/telemetry.py`:

```python
from workflows.telemetry import get_telemetry_manager, initialize_telemetry

# Get the TelemetryManager singleton
telemetry = get_telemetry_manager()

# Initialize once at startup - connects to:
# - Azure Application Insights (via connection string)
# - OTLP endpoint (for Jaeger, Zipkin, etc.)
# - VS Code extension (local debugging)
telemetry.initialize_observability()
```

### 2. Creating Spans

Spans represent units of work and form the trace tree:

```python
# Agent operation span
with telemetry.create_agent_span(
    "CustomerDataAgent",        # agent name
    "data_retrieval",           # operation type
    transaction_id="TX123",     # custom attributes
    customer_id="CUST456",
) as span:
    span.add_event("Starting analysis")     # Mark key moments
    span.set_attribute("result.count", 5)   # Add data
    # ... do work ...
    span.record_exception(e)                # Capture errors
```

### 3. Business Events

Domain-specific events attached to spans:

```python
send_business_event("fraud_detection.risk_analysis.completed", {
    "transaction_id": "TX123",
    "risk_score": 85,
    "risk_level": "HIGH",
})
```

### 4. Metrics

Counters and histograms for aggregated analysis. See the [Business Metrics](#business-metrics) section below for the full list of available metrics.

## Trace Flow

The workflow creates a hierarchical trace structure:

1. **Workflow Start** → Creates root span for the entire workflow
2. **CustomerDataAgent** → Child span for data retrieval operations
3. **RiskAnalyserAgent** → Child span for risk analysis with score attributes
4. **FraudAlertAgent** → Child span for alert creation decisions

Each agent span includes:
- Processing time measurements
- Business events for start/completion
- Error recording with stack traces
- Custom attributes (transaction_id, customer_id, risk scores)

## Understanding `set_attribute` vs `add_event`

### `span.set_attribute(key, value)`

**Attributes** are key-value pairs that describe the span itself—metadata about what the span represents.

```python
span.set_attribute("customer_id", "CUST123")      # Who/what
span.set_attribute("risk.score", 85)              # Results
span.set_attribute("ai.processing_time", 1.23)   # Performance
span.set_attribute("db.operation", "query")       # Technical context
```

**Characteristics:**
- Static data that applies to the entire span duration
- Used for filtering/grouping traces in observability tools
- Searchable in Application Insights, Jaeger, etc.
- Best for: identifiers, configuration, final results

### `span.add_event(name, attributes={})`

**Events** are timestamped log entries within a span's timeline—they mark moments when something happened.

```python
span.add_event("Starting customer lookup")
span.add_event("Cache miss, querying database")
span.add_event("Found 5 transactions", {"count": 5})
span.add_event("Risk calculation complete", {"score": 85, "level": "HIGH"})
```

**Characteristics:**
- Temporal data showing progression through the span
- Multiple events per span (like a timeline)
- Each event has its own timestamp
- Best for: debugging, tracking steps, logging milestones

## Complete Trace Hierarchy

The following diagram shows the full trace structure for a single transaction workflow:

```
Trace: fraud_detection_workflow (TX-2024-001)
│
├── Span: agent.CustomerDataAgent.data_retrieval
│   ├── Attributes:
│   │   ├── agent.name = "CustomerDataAgent"
│   │   ├── agent.operation = "data_retrieval"
│   │   ├── transaction_id = "TX-2024-001"
│   │   ├── customer_id = "CUST-456"
│   │   └── ai.processing_time = 1.25
│   │
│   ├── Events:
│   │   ├── [00:00.000] "Calling portal-hosted CustomerDataAgent"
│   │   ├── [00:00.050] business_event.fraud_detection.customer_data.started
│   │   ├── [00:00.200] Tool: get_customer_data
│   │   ├── [00:00.800] Tool: get_customer_transactions
│   │   ├── [00:01.250] business_event.fraud_detection.customer_data.completed
│   │   └── [00:01.250] "Customer data analysis completed"
│   │
│   └── Metrics:
│       └── fraud_detection.transactions.processed +1
│
├── Span: agent.RiskAnalyserAgent.risk_analysis
│   ├── Attributes:
│   │   ├── agent.name = "RiskAnalyserAgent"
│   │   ├── agent.operation = "risk_analysis"
│   │   ├── transaction_id = "TX-2024-001"
│   │   ├── customer_id = "CUST-456"
│   │   ├── ai.processing_time = 2.10
│   │   ├── risk.score = 78
│   │   ├── risk.level = "HIGH"
│   │   └── risk.recommendation = "BLOCK"
│   │
│   ├── Events:
│   │   ├── [00:01.260] "Calling portal-hosted RiskAnalyserAgent"
│   │   ├── [00:01.270] business_event.fraud_detection.risk_analysis.started
│   │   ├── [00:01.500] Tool: analyze_transaction_risk
│   │   ├── [00:03.360] business_event.fraud_detection.risk_analysis.completed
│   │   ├── [00:03.360] business_event.fraud_detection.model.prediction
│   │   └── [00:03.360] business_event.fraud_detection.customer.friction (if BLOCK/INVESTIGATE)
│   │
│   └── Metrics:
│       ├── fraud_detection.risk_score.distribution = 78
│       ├── fraud_detection.model.confidence = 0.56
│       └── fraud_detection.customer_friction +1 (if friction triggered)
│
└── Span: agent.FraudAlertAgent.alert_creation
    ├── Attributes:
    │   ├── agent.name = "FraudAlertAgent"
    │   ├── agent.operation = "alert_creation"
    │   ├── transaction_id = "TX-2024-001"
    │   ├── customer_id = "CUST-456"
    │   ├── ai.processing_time = 0.95
    │   ├── alert.created = true
    │   └── alert.severity = "HIGH"
    │
    ├── Events:
    │   ├── [00:03.370] "Calling portal-hosted FraudAlertAgent"
    │   ├── [00:03.380] business_event.fraud_detection.fraud_alert.started
    │   ├── [00:03.600] Tool: create_fraud_alert
    │   ├── [00:04.320] business_event.fraud_detection.fraud_alert.completed
    │   ├── [00:04.320] business_event.fraud_detection.fraud.prevented (if BLOCK)
    │   └── [00:04.320] business_event.fraud_detection.compliance.sar_filed (if high-risk)
    │
    └── Metrics:
        ├── fraud_detection.alerts.created +1 {severity="HIGH"}
        ├── fraud_detection.amount_blocked +5200 USD (if fraud prevented)
        └── fraud_detection.compliance.sar_filed +1 (if SAR triggered)
```

## Business Metrics

The workflow tracks business-critical metrics for operational insights and compliance reporting.

### Metrics Summary

| Metric Name | Type | Description | Triggered By |
|-------------|------|-------------|--------------|
| `fraud_detection.transactions.processed` | Counter | Transactions processed per stage | CustomerDataAgent |
| `fraud_detection.risk_score.distribution` | Histogram | Distribution of risk scores (0-100) | RiskAnalyserAgent |
| `fraud_detection.alerts.created` | Counter | Fraud alerts created, labeled by severity | FraudAlertAgent |
| `fraud_detection.amount_blocked` | Counter | Total USD blocked due to fraud prevention | FraudAlertAgent (BLOCK) |
| `fraud_detection.false_positives` | Counter | False positive detections | Manual confirmation |
| `fraud_detection.customer_friction` | Counter | Customer friction events (delays, blocks) | RiskAnalyserAgent (BLOCK/INVESTIGATE) |
| `fraud_detection.model.confidence` | Histogram | Model confidence scores (0.0-1.0) | RiskAnalyserAgent |
| `fraud_detection.compliance.sar_filed` | Counter | Suspicious Activity Report filings | FraudAlertAgent (high-risk) |

### Metric Types Explained

- **Counter**: Monotonically increasing values (e.g., total transactions processed). Use for counting events.
- **Histogram**: Distribution of values with automatic bucketing (e.g., risk score distribution). Use for measuring ranges and percentiles.

### Using Metrics in Application Insights

These metrics can be queried in Application Insights using KQL:

```kusto
// Risk score distribution over time
customMetrics
| where name == "fraud_detection.risk_score.distribution"
| summarize avg(value), percentile(value, 95) by bin(timestamp, 1h)

// Alerts by severity
customMetrics
| where name == "fraud_detection.alerts.created"
| extend severity = tostring(customDimensions["severity"])
| summarize count() by severity, bin(timestamp, 1d)
```
