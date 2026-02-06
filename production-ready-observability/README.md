# Production Ready Observability - Fraud Detection Agents

This project demonstrates production-grade observability patterns for AI agent systems through a real-world fraud detection scenario. It features three specialized AI agents—**CustomerDataAgent** (retrieves customer profiles and transaction history), **RiskAnalyserAgent** (evaluates fraud risk using regulations and policies), and **FraudAlertAgent** (creates alerts and compliance filings)—orchestrated in a sequential workflow.

**Key capabilities:**
- **End-to-end distributed tracing** with hierarchical spans for each agent operation
- **Business metrics** tracking risk scores, blocked amounts, SAR filings, and customer friction
- **Azure integration** with Application Insights, Cosmos DB, and AI Search
- **Pre-built dashboards** via an importable Application Insights workbook
- **Hands-on exercises** progressing from individual agents to full workflow orchestration and batch telemetry generation

The observability implementation showcases best practices for spans, attributes, events, and metrics—providing a reference architecture for monitoring AI agent systems in production.

## Infrastructure Deployment

### Prerequisites
- Azure CLI installed and logged in (`az login`)
- Subscription with permissions to create resources

### Deploy Resources

```bash
export RG=<your-resource-group>
export LOCATION=northcentralus

# Create resource group
az group create --name $RG --location $LOCATION

# Deploy all resources (AI Services, Cosmos DB, AI Search, App Insights)
az deployment group create \
  --resource-group $RG \
  --template-file production-ready-observability/infra/setup.bicep \
  --parameters @production-ready-observability/infra/setup.parameters.json
```

### Configure Environment

Run the setup script to populate the `.env` file with all deployed resource keys:

```bash
./infra/setup-env.sh $RG
```

### Seed Data

Populate Cosmos DB and Azure AI Search with sample data:

```bash
./data/seed_data.sh
```

This will:
- Create the `FinancialComplianceDB` database in Cosmos DB
- Create containers for `Customers` and `Transactions` data
- Import sample customer and transaction records
- Set up the `regulations-policies` index in Azure AI Search
- Upload regulatory documents for the risk analysis agent

## Exercise 1 - Run Individual Agents (standalone with Foundry registration)
```bash
python agents/customer_data_agent.py
python agents/risk_analyser_agent.py
python agents/fraud_alert_agent.py
```

Go to your new [Foundry Portal](www.ai.azure.com/nextgen) and find a first version of your 3 agents there.

## Exercise 2 - Run Workflow Agents 

### Workflow (orchestrates all 3 agents)
```bash
python workflows/workflow.py
```

This workflow orchestrates the three agents registered in the Foundry Portal in a sequential pipeline:

1. **CustomerDataAgent** retrieves customer profile and transaction history from Cosmos DB
2. **RiskAnalyserAgent** evaluates fraud risk using AI Search-indexed regulations and policies
3. **FraudAlertAgent** makes the final decision—approving, investigating, or blocking the transaction

The workflow produces comprehensive telemetry including distributed traces, business events, and metrics that flow to Application Insights for monitoring and analysis.

For detailed documentation on how distributed tracing is implemented in this workflow, including span creation, business events, metrics, and the complete trace hierarchy, see:

**[Tracing Documentation](TRACING.md)**

This guide covers:
- Telemetry initialization and the `TelemetryManager` singleton
- Creating and configuring spans for agent operations
- Understanding `set_attribute` vs `add_event`
- Business event naming conventions
- Complete trace hierarchy visualization
- All available business metrics and how to query them

## Exercise 3 - Batch Run for Telemetry Generation

Run a batch of 10 transactions to generate telemetry data for Application Insights dashboards and workbooks.

### Run Batch
```bash
cd batch_run
python batch_runner.py
```

### Output

The batch runner processes 10 transactions and generates:
- **Telemetry traces** for each transaction workflow
- **Business metrics** (risk scores, alerts, amounts blocked)
- **Batch summary events** (`fraud_detection.batch.started`, `fraud_detection.batch.completed`)
- **Console summary** with statistics


## Exercise 4 - Import Application Insights Workbook

A pre-built workbook is available for visualizing all fraud detection metrics:

1. Open your Application Insights resource in the Azure Portal
2. Navigate to **Workbooks** in the left menu
3. Click **+ New**
4. Click the **Advanced Editor** button (`</>` icon)
5. Copy the contents of `workbook/fraud-detection-workbook.json`
6. Paste into the editor and click **Apply**
7. Click **Done Editing** to save

Your workbook, now reflecting the metrics we have created and populated with our OTEL method, will look something similar to this:

![alt text](../images/workbook.png)

The workbook includes:
- **Overview Metrics**: Transactions processed, alerts created, amount blocked, SAR filings
- **Risk Analysis**: Risk score distribution and trends
- **Model Performance**: Confidence scores and top risk factors
- **Fraud Prevention**: Alerts by severity, blocked amounts over time
- **Customer Experience**: Friction events and false positives
- **Compliance**: SAR filing details and timeline
- **Agent Performance**: Processing times and success rates
- **Transaction Explorer**: Search and filter recent transactions
- **Errors & Exceptions**: Error monitoring and troubleshooting

## Exercise 5 - Explore your Traces with Grafana

## Exercise 6 - Explore the Transaction Search 

## Exercise 7 - Send the data to your BDMs

### Why Business Dashboards Matter

While Application Insights workbooks are excellent for technical teams, **Business Decision Makers (BDMs)** need access to the same observability data in tools they already use—like Power BI. This ensures that:

- **Transparency flows to leadership**: Executives can see real-time fraud detection performance without accessing Azure portals
- **Data-driven decisions**: Business metrics (amount blocked, SAR filings, alert rates) drive strategic decisions
- **Compliance visibility**: Auditors and compliance officers can verify regulatory adherence through familiar reporting tools
- **Cross-functional alignment**: Technical and business teams share a single source of truth

The observability data we've collected with OpenTelemetry isn't just for debugging—it's a business asset that demonstrates the AI system's value and trustworthiness.

### Connect Power BI to Log Analytics

#### Step 1: Get Your Log Analytics Workspace Details

1. Go to **Azure Portal** → **Log Analytics workspaces**
2. Select your workspace (e.g., `law-frauddet5db5`)
3. Note the **Workspace ID** from the Properties blade

#### Step 2: Connect Power BI Desktop

1. Open **Power BI Desktop**
2. Click **Get Data** → Search for **"Azure Data Explorer (Kusto)"**
3. Enter the cluster URL:
   ```
   https://ade.loganalytics.io/subscriptions/<subscription-id>/resourcegroups/<resource-group>/providers/microsoft.operationalinsights/workspaces/<workspace-name>
   ```
4. Leave the database field empty
5. Authenticate with your Azure AD credentials

#### Step 3: Import the Data Tables

Select these tables from your workspace:
- **AppMetrics** - Contains all business metrics (transactions, alerts, amount blocked, risk scores)
- **AppTraces** - Contains detailed event logs (SAR filings, model predictions)

> **Note**: For workspace-based Application Insights, use `AppMetrics` and `AppTraces` (not `customMetrics` and `traces`).

#### Step 4: Create a Date Column for Time Series

Since DirectQuery mode has limitations, add a custom column in Power Query:

1. **Transform data** → Select your table
2. **Add Column** → **Custom Column**
3. Name: `Date`, Formula: `DateTime.Date([TimeGenerated])`
4. **Close & Apply**

#### Step 5: Build Your Executive Dashboard

Create these key visuals for business stakeholders:

| Visual | Type | Data | Business Value |
|--------|------|------|----------------|
| Transactions Processed | Card | Sum where Name = `fraud_detection.transactions.processed` | Volume indicator |
| Fraud Alerts | Card | Sum where Name = `fraud_detection.alerts.created` | Risk exposure |
| Amount Blocked | Card | Sum where Name = `fraud_detection.amount_blocked` | Money protected |
| SAR Filings | Card | Sum where Name = `fraud_detection.compliance.sar_filed` | Compliance status |
| Alerts Over Time | Bar Chart | Date × Sum (filtered by alerts) | Trend analysis |
| Risk Score Trend | Line Chart | Date × Average Sum (filtered by risk score) | Model performance |

For this workshop, we have left you with a sample dashboard under the folder `powerbi/`. If you want to use it, go ahead. All you need to do is change the Data Source.

#### Step 6: Schedule Refresh

1. Publish to **Power BI Service**
2. Configure **Scheduled Refresh** (hourly or daily)
3. Share dashboard with BDM stakeholders




