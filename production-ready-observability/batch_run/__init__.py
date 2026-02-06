"""
Batch Run Module for Fraud Detection Workflow

Provides batch processing capabilities for running multiple fraud detection
workflows and generating telemetry data for Application Insights dashboards.
"""

from .multi_transaction_simulator import (
    run_batch_simulation,
    quick_demo,
    stress_test,
    business_day_simulation,
    custom_run,
    TransactionResult,
    BatchRunSummary,
    AVAILABLE_TRANSACTIONS,
)

__all__ = [
    "run_batch_simulation",
    "quick_demo",
    "stress_test",
    "business_day_simulation",
    "custom_run",
    "TransactionResult",
    "BatchRunSummary",
    "AVAILABLE_TRANSACTIONS",
]
