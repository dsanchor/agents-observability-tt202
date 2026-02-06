#!/usr/bin/env python3
"""
Batch Runner for Fraud Detection Workflow

Runs 10 transactions through the fraud detection workflow to generate
telemetry data for Application Insights dashboards and workbooks.

Usage:
    python batch_runner.py
"""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from multi_transaction_simulator import run_batch_simulation


def print_banner():
    """Print the CLI banner."""
    banner = """
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║   🔍 FRAUD DETECTION BATCH RUNNER                                    ║
║                                                                      ║
║   Process 10 transactions for Application Insights dashboards        ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
    """
    print(banner)


async def main():
    """Run 10 transactions through the fraud detection workflow."""
    print_banner()
    
    print("📊 Starting batch run with 10 transactions...")
    print("-" * 70)
    
    try:
        summary = await run_batch_simulation(
            num_transactions=10,
            delay_between=1.0,
            randomize_delay=False,
            shuffle_transactions=False,
        )
        
        print("\n✅ Batch run completed successfully!")
        print("📊 View results in Application Insights or the workbook dashboard.")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Batch run interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Error during batch run: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
