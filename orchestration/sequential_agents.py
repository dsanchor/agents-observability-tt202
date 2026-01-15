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
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential

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

    def __init__(self, agent: ChatAgent, id: str = "ResearcherAgent"):
        self.agent = agent
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

    def __init__(self, agent: ChatAgent, id: str = "WriterAgent"):
        self.agent = agent
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

    def __init__(self, agent: ChatAgent, id: str = "ReviewerAgent"):
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

        print(f"\nReviewerAgent output:")
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

            # Create chat clients for the three Foundry agents
            print("Loading agents from Microsoft Foundry...")
            researcher_client = await create_chat_client_for_agent(project_client, "ResearcherAgent")
            writer_client = await create_chat_client_for_agent(project_client, "WriterAgent")
            reviewer_client = await create_chat_client_for_agent(project_client, "ReviewerAgent")
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
                .register_executor(lambda: ResearcherAgentExecutor(researcher), name="ResearcherAgent")
                .register_executor(lambda: WriterAgentExecutor(writer), name="WriterAgent")
                .register_executor(lambda: ReviewerAgentExecutor(reviewer), name="ReviewerAgent")
                # Define the sequential flow: Researcher -> Writer -> Reviewer
                .add_edge("ResearcherAgent", "WriterAgent")
                .add_edge("WriterAgent", "ReviewerAgent")
                # Set the entry point
                .set_start_executor("ResearcherAgent")
                # .set_start_executor("WriterAgent")
                .build()
            )

            task = "Research and write a comprehensive article about the impact of AI agents in software development. Include recent trends and real-world examples."

            # Run the workflow with streaming to observe events as they occur
            print("=" * 80)
            print(
                "Starting sequential workflow: ResearcherAgent -> WriterAgent -> ReviewerAgent")
            print("=" * 80)
            print(f"\nTASK: {task}\n")

            async for event in workflow.run_stream(
                ChatMessage(role="user", text=task)
            ):
                if isinstance(event, WorkflowStatusEvent):
                    if event.state == WorkflowRunState.IDLE:
                        print("\n" + "=" * 80)
                        print("✓ Workflow completed successfully")
                        print("=" * 80)
                elif isinstance(event, WorkflowOutputEvent):
                    print("\n" + "=" * 80)
                    print("FINAL CONVERSATION")
                    print("=" * 80)
                    messages = event.data
                    for i, msg in enumerate(messages, start=1):
                        name = msg.author_name or (
                            "assistant" if msg.role.value == "assistant" else "user")
                        print(f"\n{'-' * 80}\n{i:02d} [{name}]")
                        print(msg.text)

            # Allow time for async cleanup
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
