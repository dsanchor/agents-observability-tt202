# Copyright (c) Microsoft. All rights reserved.

"""
Writer Agent - Standalone Foundry Agent

Creates a professional content writer agent in Azure AI Foundry.
This agent specializes in creating well-structured, engaging content. 
"""

import asyncio
import os

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity.aio import DefaultAzureCredential


async def create_writer_agent():
    """Create a writer agent in Azure AI Foundry.

    Returns:
        A configured agent for writing content (created in Foundry)
    """
    print("="*60)
    print("CREATING WRITER AGENT IN AZURE AI FOUNDRY")
    print("="*60)

    # Verify environment variables
    if not os.environ.get("AZURE_AI_PROJECT_ENDPOINT"):
        raise ValueError(
            "AZURE_AI_PROJECT_ENDPOINT environment variable is required")
    if not os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME"):
        raise ValueError(
            "AZURE_AI_MODEL_DEPLOYMENT_NAME environment variable is required")

    async with DefaultAzureCredential() as credential:
        async with AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=credential
        ) as project_client:
            print("\nCreating Writer Agent...")

            # Create agent definition
            definition = PromptAgentDefinition(
                model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
                instructions="""You are a professional content writer.
                    Your role is to create well-structured, engaging, and informative content.
                    Write in a clear, concise style with proper formatting.
                    Always include relevant details and examples when appropriate.

                    When writing:
                    - Use proper headings and structure
                    - Write in an engaging, accessible tone
                    - Include specific examples and details
                    - Keep paragraphs focused and concise
                    - Use transitions to connect ideas smoothly"""
            )

            agent = await project_client.agents.create_version(
                agent_name="WriterAgent",
                definition=definition
            )

            print(f"✓ Writer Agent created successfully!")
            print(f"  Agent ID: {agent.id}")
            print(f"  Agent Name: {agent.name}")

            return agent


async def main() -> None:
    """Main function to create and test the writer agent."""
    try:
        # Create the agent
        agent = await create_writer_agent()

        print("\n" + "="*60)
        print("WRITER AGENT SETUP COMPLETE")
        print("="*60)
        print("\nThe agent is now available in Azure AI Foundry.")
        print("You can use it from any application by referencing:")
        print(f"  Agent Name: WriterAgent")

    except Exception as e:
        print(f"\n❌ Error:  {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
