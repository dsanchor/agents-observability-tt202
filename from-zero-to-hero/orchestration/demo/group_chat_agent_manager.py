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
)
from agent_framework_orchestrations import GroupChatBuilder
from agent_framework.azure import AzureAIProjectAgentProvider
from azure.ai.projects.aio import AIProjectClient
from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential


async def main() -> None:
    # Verify environment variables
    if not os.environ.get("AZURE_AI_PROJECT_ENDPOINT"):
        raise ValueError(
            "AZURE_AI_PROJECT_ENDPOINT environment variable is required")

    async with (
        DefaultAzureCredential() as credential,
        AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=credential
        ) as project_client,
        AzureAIProjectAgentProvider(project_client=project_client) as provider,
    ):

        print("Loading agents from Microsoft Foundry via provider.get_agent()...")
        researcher = await provider.get_agent(name="ResearcherAgentV2")
        writer = await provider.get_agent(name="WriterAgentV2")
        reviewer = await provider.get_agent(name="ReviewerAgentV2")

        coordinator_name = "CoordinatorAgentV2"
        try:
            coordinator = await provider.get_agent(name=coordinator_name)
            print(f"✓ Reusing coordinator '{coordinator_name}'")
        except ResourceNotFoundError:
            model_deployment = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
            if not model_deployment:
                raise ValueError(
                    "AZURE_AI_MODEL_DEPLOYMENT_NAME environment variable is required")

            coordinator = await provider.create_agent(
                name=coordinator_name,
                model=model_deployment,
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
            )
            print(f"✓ Created coordinator '{coordinator_name}'")

        print("✓ All agents loaded successfully\n")

        # Build workflow using RC2 API
        # Constructor params instead of fluent builder methods
        def termination_check(messages: list[Message]) -> bool:
            return sum(1 for msg in messages if str(msg.role) == "assistant") >= 6

        workflow = GroupChatBuilder(
            participants=[researcher, writer, reviewer],
            orchestrator_agent=coordinator,
            termination_condition=termination_check,
        ).build()

        task = "Research and write a comprehensive article about the impact of AI agents in software development. Include recent trends and real-world examples."

        print("Starting Group Chat with Agent-Based Manager...\n")
        print(f"TASK: {task}\n")
        print("=" * 80)

        final_conversation: list[Message] = []
        last_executor_id: str | None = None

        # RC2 API: run(stream=True) instead of run_stream()
        async for event in workflow.run(task, stream=True):
            # RC2 API: check event.type instead of isinstance()
            if event.type == "update":
                eid = event.executor_id
                if eid != last_executor_id:
                    if last_executor_id is not None:
                        print()
                    print(f"{eid}:", end=" ", flush=True)
                    last_executor_id = eid
                print(event.data, end="", flush=True)
            elif event.type == "output":
                final_conversation = cast(list[Message], event.data)

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
