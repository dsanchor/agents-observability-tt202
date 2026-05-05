# Copyright (c) Microsoft. All rights reserved.

"""
Sample: Sequential workflow with Foundry agents wrapped by executors.

Sequential Workflow: ResearcherAgent -> WriterAgent -> ReviewerAgent

Prerequisites:
- FOUNDRY_PROJECT_ENDPOINT (or AZURE_AI_PROJECT_ENDPOINT) configured
- Foundry agents created and reachable by name
"""

import asyncio
import os
from typing import Any

from agent_framework import AgentResponseUpdate, Executor, Message, WorkflowContext, handler
from agent_framework.foundry import FoundryAgent
from agent_framework.orchestrations import SequentialBuilder
from azure.identity import AzureCliCredential
from dotenv import load_dotenv


load_dotenv()


def _require_env(primary_name: str, fallback_name: str | None = None) -> str:
    value = os.getenv(primary_name)
    if value:
        return value

    if fallback_name:
        fallback_value = os.getenv(fallback_name)
        if fallback_value:
            return fallback_value

    names = primary_name if fallback_name is None else f"{primary_name} or {fallback_name}"
    raise ValueError(f"{names} environment variable is required")


def _extract_messages(response: Any) -> list[Message]:
    if response is None:
        return []

    full_conversation = getattr(response, "full_conversation", None)
    if isinstance(full_conversation, list):
        return full_conversation

    messages = getattr(response, "messages", None)
    if isinstance(messages, list):
        return messages

    if isinstance(response, list):
        return response

    return []


def _display_id(event: Any, fallback: str | None = None) -> str:
    executor_id = getattr(event, "executor_id", None)
    if executor_id:
        return str(executor_id)
    if fallback:
        return fallback
    return "Agent"


class ResearcherExecutor(Executor):
    def __init__(self, agent: FoundryAgent, id: str = "ResearcherExecutor"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def run(self, messages: list[Message], ctx: WorkflowContext[list[Message]]) -> None:
        response = await self.agent.run(messages)
        next_messages = _extract_messages(response)
        await ctx.send_message(next_messages)


class WriterExecutor(Executor):
    def __init__(self, agent: FoundryAgent, id: str = "WriterExecutor"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def run(self, messages: list[Message], ctx: WorkflowContext[list[Message]]) -> None:
        response = await self.agent.run(messages)
        next_messages = _extract_messages(response)
        await ctx.send_message(next_messages)


class ReviewerExecutor(Executor):
    def __init__(self, agent: FoundryAgent, id: str = "ReviewerExecutor"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def run(self, messages: list[Message], ctx: WorkflowContext[list[Message]]) -> None:
        response = await self.agent.run(messages)
        final_messages = _extract_messages(response)
        await ctx.yield_output(final_messages)


async def main() -> None:
    endpoint = _require_env("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT")
    credential = AzureCliCredential()

    researcher = FoundryAgent(
        project_endpoint=endpoint,
        agent_name="ResearcherAgent",
        agent_version="1",
        credential=credential,
    )
    writer = FoundryAgent(
        project_endpoint=endpoint,
        agent_name="WriterAgent",
        agent_version="1",
        credential=credential,
    )
    reviewer = FoundryAgent(
        project_endpoint=endpoint,
        agent_name="ReviewerAgent",
        agent_version="1",
        credential=credential,
    )

    workflow = SequentialBuilder(
        participants=[
            ResearcherExecutor(id="Researcher", agent=researcher),
            WriterExecutor(id="Writer", agent=writer),
            ReviewerExecutor(id="Reviewer", agent=reviewer),
        ],
        chain_only_agent_responses=True,
        intermediate_outputs=True,
    ).build()

    task = (
        "Research and write a comprehensive article about the impact of AI agents "
        "in software development. Include recent trends and real-world examples."
    )

    print("=" * 80)
    print("Starting sequential workflow: ResearcherAgent -> WriterAgent -> ReviewerAgent")
    print("=" * 80)
    print(f"\nTASK: {task}\n")

    last_agent: str | None = None
    streamed_any_output = False
    async for event in workflow.run(task, stream=True):
        if event.type != "output":
            continue

        data = event.data

        if isinstance(data, AgentResponseUpdate):
            label = _display_id(event, data.author_name)
            if label != last_agent:
                last_agent = label
                print()
                print(f"{last_agent}: ", end="", flush=True)
            if data.text:
                streamed_any_output = True
                print(data.text, end="", flush=True)
            continue

        if isinstance(data, list):
            for msg in data:
                text = getattr(msg, "text", None)
                if not text:
                    continue
                author_name = getattr(msg, "author_name", None) or "assistant"
                label = _display_id(event, author_name)
                if label != last_agent:
                    last_agent = label
                    print()
                    print(f"{last_agent}: ", end="", flush=True)
                streamed_any_output = True
                print(text, end="", flush=True)
            continue

        if hasattr(data, "messages") and isinstance(data.messages, list):
            for msg in data.messages:
                text = getattr(msg, "text", None)
                if not text:
                    continue
                author_name = getattr(msg, "author_name", None) or "assistant"
                label = _display_id(event, author_name)
                if label != last_agent:
                    last_agent = label
                    print()
                    print(f"{last_agent}: ", end="", flush=True)
                streamed_any_output = True
                print(text, end="", flush=True)
            continue

        text = getattr(data, "text", None)
        if text:
            author_name = getattr(data, "author_name", None) or "assistant"
            label = _display_id(event, author_name)
            if label != last_agent:
                last_agent = label
                print()
                print(f"{last_agent}: ", end="", flush=True)
            streamed_any_output = True
            print(text, end="", flush=True)

    if not streamed_any_output:
        print("\nNo streaming chunks were emitted. Printing non-streaming outputs...\n")
        result = await workflow.run(task)
        outputs = result.get_outputs() if hasattr(result, "get_outputs") else []
        for output in outputs:
            messages = output if isinstance(output, list) else getattr(output, "messages", [])
            for msg in messages:
                text = getattr(msg, "text", None)
                if not text:
                    continue
                author_name = getattr(msg, "author_name", None) or "assistant"
                print(f"{author_name}: {text}")

    print()
    await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())