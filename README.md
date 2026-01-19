# TechTalk: E2E Observability on Multi-Agent Systems using the Microsoft Agent Framework & OTEL

## 🎯 Session Goals

- Master MAF to build and publish Agents v2 on Foundry.
- Learn multi-agent orchestration and observability with OpenTelemetry.
- Apply production-ready observability for developers and BDMs using dashboards, KPIs, and fraud detection.

## 📋 Session Abstract

This session explores advanced multi-agent development and observability using Microsoft Foundry and the Microsoft Agent Framework (MAF). Attendees will gain practical insights into building and orchestrating agents, applying observability frameworks, and leveraging real-world scenarios to deliver actionable metrics for developers and business decision-makers. 
This session also sharers the current model we are using to skill our customers on these topics.

## 🎯 Key Audience Takeaways

- Accelerate your learning curve on the newest Microsoft Agent Framework and Microsoft Foundry Agents v2
- Visualize enterprise tracing in Application Insights with built-in and custom metrics
- Create real-time dashboards for enterprise monitoring

## 🎬 Repository Flow

### From Zero to Hero – Observability for Multi-Agent Development

👉 **[Detailed Guide: From Zero to Hero →](./from-zero-to-hero/README.md)**

**Building Foundry Agents with Microsoft Agent Framework**

Using latest MAF to build and publish new Agents v2 on Microsoft Foundry.

**Multi-Agent orchestration and local playground**

Orchestrate you agents and test them using Local Playground from the Microsoft Foundry VS Code extension.

**Hosted agents and observability on Multi-Agent Systems with OpenTelemetry**

Learn how to deploy local multi-agent orchestration to become a hosted agent in Microsoft Foundry. Enable built-in observability through OpenTelemetry.

### Production-Ready Observability of your System for Developers and BDMs

👉 **[Detailed Guide: Production-Ready Observability →](./production-ready-observability/README.md)**

**Observability Framework applied to Fraud Detection**

Understanding the spans and custom metrics creation and applying the 3-tier tracking framework (application, workflow, executor).  
Creation of the monitoring system with custom metrics adapted to our UC.

**Observability for Developers**

Leveraging Azure Application Insights to understand the default and custom metrics using the Agents Pane, Dashboards with Grafana and Custom Workbook.

**Observability for BDMs**

How are the agent metrics being propagated through our customers' organization? We will learn how to ship real-time KPIs to BDMs either using App Insights or using PowerBI's DirectQuery.

### Additional resources

Learn how we are skilling-up our customers with these additional resources from hackathons and workshops:

- 👉 **[Claims Processing with Microsoft Foundry Agents Hackathon](https://github.com/microsoft/claims-processing-hack)**
- 👉 **[Intelligent Predictive Maintenance Hackathon](https://github.com/microsoft/agentic-factory-hack)**
- 👉 **[Automated Regulatory Compliance & Audit​ Hackathon](https://github.com/microsoft/azure-trust-agents)**


## 🚀 Getting Started

1. **Prerequisites:**
   - Azure subscription
   - IDEs: there is a `devcontainer` available for this repo. You can either use:
     - GitHub Codespaces
     - VS Code with Dev Containers extension
   - Python 3.12+

2. **Choose Your Path:**
   - **Building Agents?** → Start with [From Zero to Hero](./from-zero-to-hero/README.md)
   - **Implementing Observability?** → Go to [Production-Ready Observability](./production-ready-observability/README.md)

## 📧 Contact & Support

For questions or feedback, feel free to open an issue or reach out to the maintainers.
