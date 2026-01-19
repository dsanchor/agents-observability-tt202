# Copyright (c) Microsoft. All rights reserved.

"""
Researcher Agent - Standalone Foundry Agent with Bing Grounding

Creates a research analyst agent in Microsoft Foundry with Bing search capabilities.
This agent can search the web for current information and provide comprehensive research. 
"""

import asyncio
import os
from xmlrpc import client

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition,
    BingGroundingAgentTool,
    BingGroundingSearchToolParameters,
    BingGroundingSearchConfiguration,
    ConnectionType
)
from azure.identity.aio import DefaultAzureCredential


async def get_bing_connection_id() -> str:
    """Get the Bing connection ID from Microsoft project. 

    Returns:
        The Bing connection ID

    Raises:
        ValueError: If no Bing connection is found
    """
    print("\nSearching for Bing connection in Microsoft project...")

    async with (
        DefaultAzureCredential() as credential,
        AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=credential
        ) as project_client,
    ):
        async for connection in project_client.connections. list():
            if connection.type == ConnectionType.AZURE_AI_SEARCH or "bing" in connection.name. lower():
                print(
                    f"✓ Found connection: {connection.name} (ID: {connection.id})")
                return connection.id

        raise ValueError(
            "No Bing connection found in Microsoft project. "
            "Please create a Bing resource and connect it to your Microsoft project."
        )


async def create_researcher_agent():
    """Create a researcher agent with Bing search in Microsoft Foundry.

    Returns:
        A configured agent for research tasks with web search capabilities
    """
    print("="*60)
    print("CREATING RESEARCHER AGENT IN MICROSOFT FOUNDRY")
    print("With Bing Grounding Search")
    print("="*60)

    # Verify environment variables
    if not os. environ.get("AZURE_AI_PROJECT_ENDPOINT"):
        raise ValueError(
            "AZURE_AI_PROJECT_ENDPOINT environment variable is required")
    if not os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME"):
        raise ValueError(
            "AZURE_AI_MODEL_DEPLOYMENT_NAME environment variable is required")

    # Get Bing connection ID
    try:
        bing_connection_id = await get_bing_connection_id()
    except ValueError as e:
        print(f"\n❌ {e}")
        print("\nCreating researcher agent WITHOUT Bing search...")
        bing_connection_id = None

    async with DefaultAzureCredential() as credential:
        async with AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=credential
        ) as project_client:
            print("\nCreating Researcher Agent...")

            # Prepare tools
            tools = []
            if bing_connection_id:
                tools.append(BingGroundingAgentTool(
                    bing_grounding=BingGroundingSearchToolParameters(
                        search_configurations=[
                            BingGroundingSearchConfiguration(
                                project_connection_id=bing_connection_id
                            )
                        ]
                    )
                ))
                print("✓ Bing Grounding Search tool configured")

            # Create agent definition
            definition = PromptAgentDefinition(
                model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
                instructions="""You are a thorough research analyst with access to web search.
                    Your role is to gather, analyze, and synthesize information on given topics.

                    When researching:
                    - ALWAYS use the Bing Grounding Search tool to find current, accurate information
                    - Gather information from multiple sources when possible
                    - Provide comprehensive findings with factual details
                    - Structure your research with clear sections and bullet points
                    - Always cite sources and provide context
                    - Distinguish between facts and interpretations
                    - Note the recency and reliability of information

                    Your research should be:
                    - Well-organized with clear headings
                    - Factual and evidence-based
                    - Comprehensive yet concise
                    - Properly sourced with citations""",
                tools=tools if tools else None
            )

            agent = await project_client.agents.create_version(
                agent_name="ResearcherAgent",
                definition=definition
            )

            print(f"✓ Researcher Agent created successfully!")
            print(f"  Agent ID: {agent.id}")
            print(f"  Agent Name: {agent.name}")
            print(f"  Agent Version: {agent.version}")
            if bing_connection_id:
                print(f"  Web Search:  Enabled (Bing Grounding)")
            else:
                print(f"  Web Search: Disabled (no Bing connection)")

            return agent


async def main() -> None:
    """Main function to create and test the researcher agent."""
    try:
        # Create the agent
        agent = await create_researcher_agent()

        print("\n" + "="*60)
        print("RESEARCHER AGENT SETUP COMPLETE")
        print("="*60)
        print("\nThe agent is now available in Microsoft Foundry.")
        print("You can use it from any application by referencing:")
        print(f"  Agent Name: ResearcherAgent")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
