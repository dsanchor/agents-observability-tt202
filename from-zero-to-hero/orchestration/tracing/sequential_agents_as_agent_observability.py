# Copyright (c) Microsoft. All rights reserved.

import asyncio
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
from agent_framework.azure import AzureAIClient
from agent_framework.observability import configure_otel_providers, get_tracer
from opentelemetry.trace import SpanKind
from opentelemetry.trace.span import format_trace_id
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential
from azure.ai.agentserver.agentframework import from_agent_framework

"""
Sample: Sequential workflow with Foundry agents using Executors

Sequential Workflow: ResearcherAgent -> WriterAgent -> ReviewerAgent

This workflow orchestrates three Azure agents in sequence:
1. ResearcherAgent: Processes the initial user message using web search
2. WriterAgent: Takes the researcher's output and generates content
3. ReviewerAgent: Reviews and finalizes the content

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
        use_latest_version=True,
    )


class ResearcherAgentExecutor(Executor):
    """
    First agent in the sequential workflow.
    Processes the initial user message and passes results to the next agent.
    """

    agent: ChatAgent

    def __init__(self, project_client: AIProjectClient, id: str = "ResearcherAgent"):
        # Create the researcher agent with Foundry client
        client = AzureAIClient(
            project_client=project_client,
            agent_name="ResearcherAgent",
            use_latest_version=True,
        )
        self.agent = ChatAgent(
            name="Researcher",
            description="Collects relevant information using web search",
            chat_client=client,
        )
        super().__init__(id=id)

    @handler
    async def handle(self, message: ChatMessage | list[ChatMessage], ctx: WorkflowContext[list[ChatMessage]]) -> None:
        """
        Handle the initial message and forward the conversation to WriterAgent.

        Args:
            message: The initial user message
            ctx: Workflow context for sending messages to downstream agents
        """
        if isinstance(message, list):
            messages = message
        else:
            messages = [message]

        response = await self.agent.run(messages)

        print(f"\nResearcherAgent output:")
        print(f"{response.messages[-1].text[:500]}..." if len(
            response.messages[-1].text) > 500 else response.messages[-1].text)

        messages.extend(response.messages)
        await ctx.send_message(messages)


class WriterAgentExecutor(Executor):
    """
    Second agent in the sequential workflow.
    Receives output from ResearcherAgent and generates content.
    """

    agent: ChatAgent

    def __init__(self, project_client: AIProjectClient, id: str = "WriterAgent"):
        # Create the writer agent with Foundry client
        client = AzureAIClient(
            project_client=project_client,
            agent_name="WriterAgent",
            use_latest_version=True,
        )
        self.agent = ChatAgent(
            name="Writer",
            description="Creates well-structured content based on research",
            chat_client=client,
        )
        super().__init__(id=id)

    @handler
    async def handle(self, messages: list[ChatMessage], ctx: WorkflowContext[list[ChatMessage]]) -> None:
        """
        Process the researcher's output and forward to ReviewerAgent.

        Args:
            message: Message or conversation history from ResearcherAgent
            ctx: Workflow context for sending messages to downstream agents
        """
        response = await self.agent.run(messages)

        print(f"\nWriterAgent output:")
        print(f"{response.messages[-1].text[:500]}..." if len(
            response.messages[-1].text) > 500 else response.messages[-1].text)

        messages.extend(response.messages)
        await ctx.send_message(messages)


class ReviewerAgentExecutor(Executor):
    """
    Third and final agent in the sequential workflow.
    Reviews the content and yields the final output.
    """

    agent: ChatAgent

    def __init__(self, project_client: AIProjectClient, id: str = "ReviewerAgent"):
        # Create the reviewer agent with Foundry client
        client = AzureAIClient(
            project_client=project_client,
            agent_name="ReviewerAgent",
            use_latest_version=True,
        )
        self.agent = ChatAgent(
            name="Reviewer",
            description="Evaluates content quality and provides constructive feedback",
            chat_client=client,
        )
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

        print(f"\nReviewerAgent output:")
        print(f"{response.messages[-1].text[:500]}..." if len(
            response.messages[-1].text) > 500 else response.messages[-1].text)

        # Yield the final conversation
        messages.extend(response.messages)
        await ctx.yield_output(messages)


async def main() -> None:

    ### Set up for OpenTelemetry tracing ###
    configure_otel_providers(
        vs_code_extension_port=4319,  # AI Toolkit gRPC port
        enable_sensitive_data=True  # Enable capturing prompts and completions
    )
    ### Set up for OpenTelemetry tracing ###

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

            print("Building sequential workflow with Foundry agents...\n")

            # Build the workflow using the executor pattern
            # Executors will create their agents during initialization
            workflow = (
                WorkflowBuilder()
                # Register executors with lazy instantiation, passing project_client
                .register_executor(lambda: ResearcherAgentExecutor(project_client), name="ResearcherAgent")
                .register_executor(lambda: WriterAgentExecutor(project_client), name="WriterAgent")
                .register_executor(lambda: ReviewerAgentExecutor(project_client), name="ReviewerAgent")
                # Define the sequential flow: Researcher -> Writer -> Reviewer
                .add_edge("ResearcherAgent", "WriterAgent")
                .add_edge("WriterAgent", "ReviewerAgent")
                # Set the entry point
                .set_start_executor("ResearcherAgent")
                .build()
            )

            # make the workflow an agent and ready to be hosted
            agentwf = workflow.as_agent()
            await from_agent_framework(agentwf).run_async()


if __name__ == "__main__":
    asyncio.run(main())
