# Copyright (c) Microsoft. All rights reserved.

import logging
from azure.monitor.opentelemetry import configure_azure_monitor
from azure.ai.projects.aio import AIProjectClient
from agent_framework.observability import create_resource, enable_instrumentation

logger = logging.getLogger(__name__)


async def configure_azure_monitor_tracing(project_client: AIProjectClient) -> bool:
    """
    Configure Azure Monitor tracing for the application.
    
    This will enable tracing and configure the application to send telemetry data to the
    Application Insights instance attached to the Azure AI project.
    This will override any existing configuration.
    
    Args:
        project_client: The AIProjectClient instance to get the connection string from
        
    Returns:
        True if tracing was configured successfully, False otherwise
    """
    try:
        conn_string = await project_client.telemetry.get_application_insights_connection_string()
    except Exception:
        logger.warning(
            "No Application Insights connection string found for the Azure AI Project. "
            "Please ensure Application Insights is configured in your Azure AI project, "
            "or call configure_otel_providers() manually with custom exporters."
        )
        return False
    
    configure_azure_monitor(
        connection_string=conn_string,
        enable_live_metrics=True,
        resource=create_resource(),
        enable_performance_counters=False,
    )
    # This call is not necessary if you have the environment variable ENABLE_INSTRUMENTATION=true set
    # If not or set to false, or if you want to enable or disable sensitive data collection, call this function.
    enable_instrumentation(enable_sensitive_data=True)
    
    return True
