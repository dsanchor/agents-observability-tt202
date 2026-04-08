# Copyright (c) Microsoft. All rights reserved.

"""
Sample: Sequential workflow with Foundry agents (RC2 API)

Sequential Workflow: ResearcherAgentV2 -> WriterAgentV2 -> ReviewerAgentV2

This workflow orchestrates three Azure agents in sequence:
1. ResearcherAgentV2: Processes the initial user message using web search
2. WriterAgentV2: Takes the researcher's output and generates content
3. ReviewerAgentV2: Reviews and finalizes the content

Prerequisites:
- AZURE_AI_PROJECT_ENDPOINT environment variable configured
- Agents (ResearcherAgentV2, WriterAgentV2, ReviewerAgentV2) created in Foundry
"""

import asyncio
import os
from typing import Never

from agent_framework import (
    Agent,
    Message,
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowRunState,
    handler,
)
from agent_framework.azure import AzureAIProjectAgentProvider
from azure.identity.aio import DefaultAzureCredential


class ResearcherExecutor(Executor):
    """
    First agent in the sequential workflow.
    Processes the initial user message and passes results to the next agent.
    """

    agent: Agent

    def __init__(self, agent: Agent, id: str = "ResearcherAgentV2"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(self, message: Message | list[Message], ctx: WorkflowContext[list[Message]]) -> None:
        """
        Handle the initial message and forward the conversation to WriterAgentV2.

        Args:
            message: The initial user message
            ctx: Workflow context for sending messages to downstream agents
        """
        messages = message if isinstance(message, list) else [message]

        response = await self.agent.run(messages)

        print(f"\n[ResearcherAgentV2] output:")
        text = response.messages[-1].text if response.messages else ""
        print(f"{text[:500]}..." if len(text) > 500 else text)

        messages.extend(response.messages)
        await ctx.send_message(messages)


class WriterExecutor(Executor):
    """
    Second agent in the sequential workflow.
    Receives output from ResearcherAgentV2 and generates content.
    """

    agent: Agent

    def __init__(self, agent: Agent, id: str = "WriterAgentV2"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(self, messages: list[Message], ctx: WorkflowContext[list[Message]]) -> None:
        """
        Process the researcher's output and forward to ReviewerAgentV2.

        Args:
            messages: Conversation history from ResearcherAgentV2
            ctx: Workflow context for sending messages to downstream agents
        """
        response = await self.agent.run(messages)

        print(f"\n[WriterAgentV2] output:")
        text = response.messages[-1].text if response.messages else ""
        print(f"{text[:500]}..." if len(text) > 500 else text)

        messages.extend(response.messages)
        await ctx.send_message(messages)


class ReviewerExecutor(Executor):
    """
    Third and final agent in the sequential workflow.
    Reviews the content and yields the final output.
    """

    agent: Agent

    def __init__(self, agent: Agent, id: str = "ReviewerAgentV2"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(self, messages: list[Message], ctx: WorkflowContext[Never, list[Message]]) -> None:
        """
        Review the final content and yield the workflow output.

        Args:
            messages: Full conversation history from previous agents
            ctx: Workflow context for yielding final output
        """
        response = await self.agent.run(messages)

        print(f"\n[ReviewerAgentV2] output:")
        text = response.messages[-1].text if response.messages else ""
        print(f"{text[:500]}..." if len(text) > 500 else text)

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

    async with (
        DefaultAzureCredential() as credential,
        AzureAIProjectAgentProvider(
            project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=credential,
        ) as provider,
    ):
        # Load pre-existing Foundry agents through the provider.
        print("Loading agents from Microsoft Foundry via provider.get_agent()...")
        researcher = await provider.get_agent(name="ResearcherAgentV2")
        writer = await provider.get_agent(name="WriterAgentV2")
        reviewer = await provider.get_agent(name="ReviewerAgentV2")
        print("✓ All agents loaded successfully\n")

        # Create executors wrapping the agents
        researcher_executor = ResearcherExecutor(researcher)
        writer_executor = WriterExecutor(writer)
        reviewer_executor = ReviewerExecutor(reviewer)

        # Build the workflow using RC2 API
        # start_executor is now a required constructor parameter
        # add_edge takes executor instances directly (auto-registered)
        workflow = (
            WorkflowBuilder(
                name="SequentialResearchWorkflow",
                description="Research -> Write -> Review sequential workflow",
                start_executor=researcher_executor,
            )
            .add_edge(researcher_executor, writer_executor)
            .add_edge(writer_executor, reviewer_executor)
            .build()
        )

        task = "Research and write a comprehensive article about the impact of AI agents in software development. Include recent trends and real-world examples."

        # Run the workflow with streaming (RC2 API: run(stream=True) instead of run_stream())
        print("=" * 80)
        print("Starting sequential workflow: ResearcherAgentV2 -> WriterAgentV2 -> ReviewerAgentV2")
        print("=" * 80)
        print(f"\nTASK: {task}\n")

        async for event in workflow.run(Message(role="user", text=task), stream=True):
            # RC2 API: check event.type instead of isinstance()
            if event.type == "status" and event.state == WorkflowRunState.IDLE:
                print("\n" + "=" * 80)
                print("✓ Workflow completed successfully")
                print("=" * 80)
            elif event.type == "output":
                print("\n" + "=" * 80)
                print("FINAL CONVERSATION")
                print("=" * 80)
                messages = event.data
                for i, msg in enumerate(messages, start=1):
                    # RC2: role is a string, not an enum
                    role = msg.role.value if hasattr(msg.role, 'value') else str(msg.role)
                    name = msg.author_name or ("assistant" if role == "assistant" else "user")
                    print(f"\n{'-' * 80}\n{i:02d} [{name}]")
                    print(msg.text)

        # Allow time for async cleanup
        await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())