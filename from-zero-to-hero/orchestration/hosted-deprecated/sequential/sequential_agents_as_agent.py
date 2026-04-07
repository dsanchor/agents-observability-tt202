# Copyright (c) Microsoft. All rights reserved.

import asyncio
from asyncio.log import logger
import os
from typing import Never

from agent_framework import (
    ChatAgent,
    ChatMessage,
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowOutputEvent,
    WorkflowStatusEvent,
    WorkflowRunState,
    handler,
)
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.ai.projects.aio import AIProjectClient
from observability import configure_azure_monitor_tracing
from azure.identity.aio import DefaultAzureCredential
from azure.ai.agentserver.agentframework import from_agent_framework


"""
Sample: Sequential workflow with Foundry agents using Executors

Sequential Workflow: ResearcherAgentV2 -> WriterAgentV2 -> ReviewerAgentV2

This workflow orchestrates three Azure agents in sequence:
1. ResearcherAgentV2: Processes the initial user message using web search
2. WriterAgentV2: Takes the researcher's output and generates content
3. ReviewerAgentV2: Reviews and finalizes the content

Prerequisites:
- AZURE_AI_PROJECT_ENDPOINT environment variable configured
- Agents (ResearcherAgentV2, WriterAgentV2, ReviewerAgentV2) created in Foundry
"""


async def create_chat_client_for_agent(
    project_client: AIProjectClient,
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


class ResearcherAgentV2Executor(Executor):
    """
    First agent in the sequential workflow.
    Processes the initial user message and passes results to the next agent.
    """

    agent: ChatAgent

    def __init__(self, agent: ChatAgent, id: str = "ResearcherAgentV2"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(self, message: ChatMessage | list[ChatMessage], ctx: WorkflowContext[list[ChatMessage]]) -> None:
        """
        Handle the initial message and forward the conversation to WriterAgentV2.

        Args:
            message: The initial user message
            ctx: Workflow context for sending messages to downstream agents
        """
        if isinstance(message, list):
            messages = message
        else:
            messages = [message]

        response = await self.agent.run(messages)

        print(f"\nResearcherAgentV2 output:")
        print(f"{response.messages[-1].text[:500]}..." if len(
            response.messages[-1].text) > 500 else response.messages[-1].text)

        messages.extend(response.messages)
        await ctx.send_message(messages)


class WriterAgentV2Executor(Executor):
    """
    Second agent in the sequential workflow.
    Receives output from ResearcherAgentV2 and generates content.
    """

    agent: ChatAgent

    def __init__(self, agent: ChatAgent, id: str = "WriterAgentV2"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(self, messages: list[ChatMessage], ctx: WorkflowContext[list[ChatMessage]]) -> None:
        """
        Process the researcher's output and forward to ReviewerAgentV2.

        Args:
            message: Message or conversation history from ResearcherAgentV2
            ctx: Workflow context for sending messages to downstream agents
        """

        response = await self.agent.run(messages)

        print(f"\nWriterAgentV2 output:")
        print(f"{response.messages[-1].text[:500]}..." if len(
            response.messages[-1].text) > 500 else response.messages[-1].text)

        messages.extend(response.messages)
        await ctx.send_message(messages)


class ReviewerAgentV2Executor(Executor):
    """
    Third and final agent in the sequential workflow.
    Reviews the content and yields the final output.
    """

    agent: ChatAgent

    def __init__(self, agent: ChatAgent, id: str = "ReviewerAgentV2"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(self, messages: list[ChatMessage], ctx: WorkflowContext[Never, list[ChatMessage]]) -> None:
        """
        Review the final content and yield the workflow output.

        Args:
            message: Message or full conversation history from previous agents
            ctx: Workflow context for yielding final output
        """
        response = await self.agent.run(messages)

        print(f"\nReviewerAgentV2 output:")
        print(f"{response.messages[-1].text[:500]}..." if len(
            response.messages[-1].text) > 500 else response.messages[-1].text)

        # Yield the final conversation
        messages.extend(response.messages)
        await ctx.yield_output(messages)


async def main() -> None:
    """
    Build and run the sequential workflow using agents from Microsoft Foundry.
    """

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
            print("Loading agents from deployment...")
            researcher_client = await create_chat_client_for_agent(project_client)
            writer_client = await create_chat_client_for_agent(project_client)
            reviewer_client = await create_chat_client_for_agent(project_client)
            print("✓ All agents loaded successfully\n")

            # Create agents using the Foundry clients
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

            # Build the workflow using the executor pattern
            # This mirrors the sequential structure: Researcher -> Writer -> Reviewer
            workflow = (
                WorkflowBuilder()
                # Register executors with lazy instantiation
                .register_executor(lambda: ResearcherAgentV2Executor(researcher), name="ResearcherAgentV2")
                .register_executor(lambda: WriterAgentV2Executor(writer), name="WriterAgentV2")
                .register_executor(lambda: ReviewerAgentV2Executor(reviewer), name="ReviewerAgentV2")
                # Define the sequential flow: Researcher -> Writer -> Reviewer
                .add_edge("ResearcherAgentV2", "WriterAgentV2")
                .add_edge("WriterAgentV2", "ReviewerAgentV2")
                # Set the entry point
                .set_start_executor("ResearcherAgentV2")
                .build()
            )

            # make the workflow an agent and ready to be hosted
            agentwf = workflow.as_agent()
            await from_agent_framework(agentwf).run_async()

if __name__ == "__main__":
    asyncio.run(main())
