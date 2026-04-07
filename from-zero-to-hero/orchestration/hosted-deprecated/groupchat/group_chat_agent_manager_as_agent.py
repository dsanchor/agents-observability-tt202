# Copyright (c) Microsoft. All rights reserved.

import asyncio
import logging
import os
from typing import cast

from agent_framework import (
    AgentRunUpdateEvent,
    ChatAgent,
    ChatMessage,
    GroupChatBuilder,
    Role,
    WorkflowOutputEvent,
)
from agent_framework.azure import AzureOpenAIResponsesClient, AzureOpenAIChatClient
from observability import configure_azure_monitor_tracing
from azure.ai.projects.aio import AIProjectClient
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential
from azure.ai.agentserver.agentframework import from_agent_framework


"""
Sample: Group Chat with Agent-Based Manager

What it does:
- Demonstrates the new set_manager() API for agent-based coordination
- Manager is a full ChatAgent with access to tools, context, and observability
- Coordinates a researcher, writer, and reviewer agent to solve tasks collaboratively
- Uses agents created in Microsoft Foundry

Prerequisites:
- AZURE_AI_PROJECT_ENDPOINT environment variable configured
- Agents (ResearcherAgentV2, WriterAgentV2, ReviewerAgentV2) created in Foundry
"""


async def create_chat_client_for_agent(
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


async def create_chat_client_for_coordinator(
    project_client: AIProjectClient
) -> AzureOpenAIResponsesClient:
    """Create an AzureOpenAIResponsesClient for the coordinator agent.

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


async def main() -> None:


    # Verify environment variables
    if not os.environ.get("AZURE_AI_PROJECT_ENDPOINT"):
        raise ValueError(
            "AZURE_AI_PROJECT_ENDPOINT environment variable is required")

    async with DefaultAzureCredential() as credential:
        async with AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=credential
        ) as project_client:
            
            # Configure Azure Monitor tracing
            if not await configure_azure_monitor_tracing(project_client):
                return

            # Create chat clients for the three Foundry agents
            print("Loading agents from Microsoft Foundry...")
            researcher_client = await create_chat_client_for_agent(project_client, "ResearcherAgentV2")
            writer_client = await create_chat_client_for_agent(project_client, "WriterAgentV2")
            reviewer_client = await create_chat_client_for_agent(project_client, "ReviewerAgentV2")
            coordinator_client = await create_chat_client_for_coordinator(project_client)
            print("✓ All agents loaded successfully\n")

            # Create coordinator agent with structured output for speaker selection
            # Note: response_format is enforced to ManagerSelectionResponse by set_manager()
            coordinator = ChatAgent(
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
                chat_client=coordinator_client,
            )

            researcher = ChatAgent(
                name="ResearcherV2",
                description="Collects relevant information using web search",
                chat_client=researcher_client,
            )

            writer = ChatAgent(
                name="WriterV2",
                description="Creates well-structured content based on research",
                chat_client=writer_client,
            )

            reviewer = ChatAgent(
                name="ReviewerV2",
                description="Evaluates content quality and provides constructive feedback",
                chat_client=reviewer_client,
            )

            workflow = (
                GroupChatBuilder()
                .set_manager(coordinator)
                .with_termination_condition(lambda messages: sum(1 for msg in messages if msg.role == Role.ASSISTANT) >= 6)
                .participants([researcher, writer, reviewer])
                .build()
            )

            # make the workflow an agent and ready to be hosted
            agentwf = workflow.as_agent()
            await from_agent_framework(agentwf).run_async()


if __name__ == "__main__":
    asyncio.run(main())
