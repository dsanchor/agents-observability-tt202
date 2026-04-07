# Copyright (c) Microsoft. All rights reserved.

"""
Sample: Group Chat with Agent-Based Manager (RC2 API)

What it does:
- Demonstrates the orchestrator_agent API for agent-based coordination
- Manager is a full Agent with access to tools, context, and observability
- Coordinates a researcher, writer, and reviewer agent to solve tasks collaboratively
- Uses agents created in Microsoft Foundry

Prerequisites:
- AZURE_AI_PROJECT_ENDPOINT environment variable configured
- Agents (ResearcherAgentV2, WriterAgentV2, ReviewerAgentV2) created in Foundry
"""

import asyncio
import os
from typing import cast

from agent_framework import (
    Agent,
    Message,
    WorkflowRunState,
)
from agent_framework_orchestrations import GroupChatBuilder
from agent_framework.azure import AzureOpenAIResponsesClient
from agent_framework.observability import configure_otel_providers
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential
from azure.ai.agentserver.agentframework import from_agent_framework

async def create_client_for_agent(
    project_client: AIProjectClient
) -> AzureOpenAIResponsesClient:
    """Create an AzureOpenAIResponsesClient for orchestrated agents.

    Args:
        project_client: The AIProjectClient instance

    Returns:
        Configured AzureOpenAIResponsesClient for the agent
    """
    model_deployment = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    if not model_deployment:
        raise ValueError(
            "AZURE_AI_MODEL_DEPLOYMENT_NAME environment variable is required")

    return AzureOpenAIResponsesClient(
        project_client=project_client,
        deployment_name=model_deployment,
    )


async def create_client_for_coordinator(
    project_client: AIProjectClient
) -> AzureOpenAIResponsesClient:
    """Create an AzureOpenAIResponsesClient for the coordinator agent.

    Args:
        project_client: The AIProjectClient instance

    Returns:
        Configured AzureOpenAIResponsesClient for the coordinator
    """
    model_deployment = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    if not model_deployment:
        raise ValueError(
            "AZURE_AI_MODEL_DEPLOYMENT_NAME environment variable is required")

    return AzureOpenAIResponsesClient(
        project_client=project_client,
        deployment_name=model_deployment,
    )


async def main() -> None:
    # Set up OpenTelemetry tracing for Agent Framework and AI Toolkit.
    ai_toolkit_port = int(os.environ.get("AI_TOOLKIT_OTLP_GRPC_PORT", "4319"))
    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://localhost:{ai_toolkit_port}")
    configure_otel_providers(
        vs_code_extension_port=ai_toolkit_port,
        enable_sensitive_data=True,
    )

    # Verify environment variables
    if not os.environ.get("AZURE_AI_PROJECT_ENDPOINT"):
        raise ValueError(
            "AZURE_AI_PROJECT_ENDPOINT environment variable is required")

    async with DefaultAzureCredential() as credential:
        async with AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=credential
        ) as project_client:

            # Create clients for the three orchestrated agents
            print("Loading agents from deployment...")
            researcher_client = await create_client_for_agent(project_client)
            writer_client = await create_client_for_agent(project_client)
            reviewer_client = await create_client_for_agent(project_client)
            coordinator_client = await create_client_for_coordinator(project_client)
            print("✓ All agents loaded successfully\n")

            # Create coordinator agent (RC2 API: client= instead of chat_client=)
            coordinator = Agent(
                name="Coordinator",
                description="Coordinates multi-agent collaboration by selecting speakers",
                instructions="""
                You coordinate a team conversation to solve the user's task.

                Review the conversation history and select the next participant to speak.

                Guidelines:
                - Start with Researcher to gather information using web search
                - Then have Writer create a draft based on the research
                - Have Reviewer evaluate the draft and provide feedback
                - Allow Writer to refine based on feedback if needed
                - Only finish after all three have contributed meaningfully
                - Allow for multiple rounds if the task requires it
                """,
                client=coordinator_client,
            )

            researcher = Agent(
                name="ResearcherV2",
                description="Collects relevant information using web search",
                client=researcher_client,
            )

            writer = Agent(
                name="WriterV2",
                description="Creates well-structured content based on research",
                client=writer_client,
            )

            reviewer = Agent(
                name="ReviewerV2",
                description="Evaluates content quality and provides constructive feedback",
                client=reviewer_client,
            )

            # Build workflow using RC2 API
            # Constructor params instead of fluent builder methods
            def termination_check(messages: list[Message]) -> bool:
                return sum(1 for msg in messages if str(msg.role) == "assistant") >= 6

            workflow = GroupChatBuilder(
                participants=[researcher, writer, reviewer],
                orchestrator_agent=coordinator,
                termination_condition=termination_check,
            ).build()

            # make the workflow an agent and ready to be hosted
            agentwf = workflow.as_agent()
            await from_agent_framework(agentwf).run_async()

if __name__ == "__main__":
    asyncio.run(main())