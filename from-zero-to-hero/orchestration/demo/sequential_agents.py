# Copyright (c) Microsoft. All rights reserved.

"""
Sample: Sequential workflow with Foundry agents using the current SDK.

Sequential Workflow: ResearcherAgent -> WriterAgent -> ReviewerAgent

Prerequisites:
- FOUNDRY_PROJECT_ENDPOINT (or AZURE_AI_PROJECT_ENDPOINT) configured
- Foundry agents created and reachable by name
"""

import asyncio
import os

try:
    from agent_framework import AgentResponseUpdate
except ImportError:
    AgentResponseUpdate = None

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


async def main() -> None:
    """
    Build and run the sequential workflow using agents from Microsoft Foundry.
    """
    endpoint = _require_env("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT")
    credential = AzureCliCredential()
    researcher_name = "ResearcherAgent"
    writer_name = "WriterAgent"
    reviewer_name = "ReviewerAgent"

    researcher = FoundryAgent(
        project_endpoint=endpoint,
        agent_name=researcher_name,
        agent_version="1",
        credential=credential,
    )
    writer = FoundryAgent(
        project_endpoint=endpoint,
        agent_name=writer_name,
        agent_version="1",
        credential=credential,
    )
    reviewer = FoundryAgent(
        project_endpoint=endpoint,
        agent_name=reviewer_name,
        agent_version="1",
        credential=credential,
    )

    workflow = SequentialBuilder(
        participants=[researcher, writer, reviewer],
        chain_only_agent_responses=True,
        intermediate_outputs=True,
    ).build()

    task = (
        "Research and write a comprehensive article about the impact of AI agents "
        "in software development. Include recent trends and real-world examples."
    )

    print("=" * 80)
    print(f"Starting sequential workflow: {researcher_name} -> {writer_name} -> {reviewer_name}")
    print("=" * 80)
    print(f"\nTASK: {task}\n")

    last_agent: str | None = None
    expected_names = [researcher_name, writer_name, reviewer_name]
    executor_name_map: dict[str, str] = {}
    next_name_index = 0

    async for event in workflow.run(task, stream=True):
        if event.type == "output" and AgentResponseUpdate and isinstance(event.data, AgentResponseUpdate):
            display_name = event.data.author_name or ""
            if not display_name or display_name == "UnnamedAgent":
                executor_id = getattr(event, "executor_id", None)
                if executor_id:
                    if executor_id not in executor_name_map:
                        if next_name_index < len(expected_names):
                            executor_name_map[executor_id] = expected_names[next_name_index]
                            next_name_index += 1
                        else:
                            executor_name_map[executor_id] = str(executor_id)
                    display_name = executor_name_map[executor_id]
                else:
                    display_name = "Agent"

            if display_name != last_agent:
                last_agent = display_name
                print()
                print(f"{last_agent}: ", end="", flush=True)
            if event.data.text:
                print(event.data.text, end="", flush=True)

    await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())