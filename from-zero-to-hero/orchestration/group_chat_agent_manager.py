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
from agent_framework.azure import AzureAIClient, AzureOpenAIChatClient
from azure.ai.projects.aio import AIProjectClient
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential

logging.basicConfig(level=logging.INFO)

"""
Sample: Group Chat with Agent-Based Manager

What it does:
- Demonstrates the new set_manager() API for agent-based coordination
- Manager is a full ChatAgent with access to tools, context, and observability
- Coordinates a researcher, writer, and reviewer agent to solve tasks collaboratively
- Uses agents created in Microsoft Foundry

Prerequisites:
- AZURE_AI_PROJECT_ENDPOINT environment variable configured
- Agents (ResearcherAgent, WriterAgent, ReviewerAgent) created in Foundry
"""


async def create_chat_client_for_agent(
    project_client: AIProjectClient,
    agent_name: str
) -> AzureAIClient:
    """Create an AzureAIClient for a Foundry agent.

    Args:
        project_client: The AIProjectClient instance
        agent_name: The name of the agent in Foundry

    Returns:
        Configured AzureAIClient for the agent
    """

    return AzureAIClient(
        project_client=project_client,
        agent_name=agent_name,
        # Property agent_version is required for existing agents.
        # If this property is not configured, the client will try to create a new agent using
        # provided agent_name.
        # It's also possible to leave agent_version empty but set use_latest_version=True.
        # This will pull latest available agent version and use that version for operations.
        # agent_version=version,
        use_latest_version=True,
    )


async def create_chat_client_for_coordinator(
    project_client: AIProjectClient
) -> AzureAIClient:
    """Create an AzureAIClient for the coordinator agent.

    Args:
        project_client: The AIProjectClient instance

    Returns:
        Configured AzureAIClient for the agent
    """

    # Get model deployment name from environment variable
    model_deployment = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    if not model_deployment:
        raise ValueError(
            "AZURE_AI_MODEL_DEPLOYMENT_NAME environment variable is required")

    return AzureAIClient(
        project_client=project_client,
        model_deployment_name=model_deployment,
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

            # Create chat clients for the three Foundry agents
            print("Loading agents from Microsoft Foundry...")
            researcher_client = await create_chat_client_for_agent(project_client, "ResearcherAgent")
            writer_client = await create_chat_client_for_agent(project_client, "WriterAgent")
            reviewer_client = await create_chat_client_for_agent(project_client, "ReviewerAgent")
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
                name="Researcher",
                description="Collects relevant information using web search",
                chat_client=researcher_client,
            )

            writer = ChatAgent(
                name="Writer",
                description="Creates well-structured content based on research",
                chat_client=writer_client,
            )

            reviewer = ChatAgent(
                name="Reviewer",
                description="Evaluates content quality and provides constructive feedback",
                chat_client=reviewer_client,
            )

            workflow = (
                GroupChatBuilder()
                .set_manager(coordinator, display_name="Orchestrator")
                .with_termination_condition(lambda messages: sum(1 for msg in messages if msg.role == Role.ASSISTANT) >= 8)
                .participants([researcher, writer, reviewer])
                .build()
            )

            task = "Research and write a comprehensive article about the impact of AI agents in software development. Include recent trends and real-world examples."

            print("Starting Group Chat with Agent-Based Manager...\n")
            print(f"TASK: {task}\n")
            print("=" * 80)

            final_conversation: list[ChatMessage] = []
            last_executor_id: str | None = None
            async for event in workflow.run_stream(task):
                if isinstance(event, AgentRunUpdateEvent):
                    eid = event.executor_id
                    if eid != last_executor_id:
                        if last_executor_id is not None:
                            print()
                        print(f"{eid}:", end=" ", flush=True)
                        last_executor_id = eid
                    print(event.data, end="", flush=True)
                elif isinstance(event, WorkflowOutputEvent):
                    final_conversation = cast(list[ChatMessage], event.data)

            if final_conversation and isinstance(final_conversation, list):
                print("\n\n" + "=" * 80)
                print("FINAL CONVERSATION")
                print("=" * 80)
                for msg in final_conversation:
                    author = getattr(msg, "author_name", "Unknown")
                    text = getattr(msg, "text", str(msg))
                    print(f"\n[{author}]")
                    print(text)
                    print("-" * 80)


if __name__ == "__main__":
    asyncio.run(main())
