"""
Multi-Transaction Simulator for Fraud Detection Workflow

This module provides batch processing capabilities for running multiple
fraud detection workflows, generating telemetry data for Application Insights
dashboards and workbooks.
"""

import asyncio
import random
import time
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflows.workflow import (
    run_fraud_detection_workflow,
    get_project_client,
    _project_client,
    _credential,
)
from workflows.telemetry import (
    initialize_telemetry,
    flush_telemetry,
    get_telemetry_manager,
    send_business_event,
)


# Available transactions from the seed data
AVAILABLE_TRANSACTIONS = [
    {"transaction_id": "TX1001", "customer_id": "CUST1001", "amount": 5200.00, "currency": "USD"},
    {"transaction_id": "TX1002", "customer_id": "CUST1002", "amount": 15000.00, "currency": "INR"},
    {"transaction_id": "TX1003", "customer_id": "CUST1003", "amount": 300.00, "currency": "CNY"},
    {"transaction_id": "TX1004", "customer_id": "CUST1004", "amount": 9900.00, "currency": "AED"},
    {"transaction_id": "TX1005", "customer_id": "CUST1005", "amount": 200.00, "currency": "EUR"},
    {"transaction_id": "TX1006", "customer_id": "CUST1006", "amount": 70.00, "currency": "GBP"},
    {"transaction_id": "TX1007", "customer_id": "CUST1007", "amount": 1800.00, "currency": "RUB"},
    {"transaction_id": "TX1008", "customer_id": "CUST1008", "amount": 40.00, "currency": "SOS"},
    {"transaction_id": "TX1009", "customer_id": "CUST1009", "amount": 90.00, "currency": "ILS"},
    {"transaction_id": "TX1010", "customer_id": "CUST1010", "amount": 600.00, "currency": "IRR"},
    {"transaction_id": "TX1011", "customer_id": "CUST1011", "amount": 220.00, "currency": "KRW"},
    {"transaction_id": "TX1012", "customer_id": "CUST1012", "amount": 1100.00, "currency": "SYP"},
    {"transaction_id": "TX1013", "customer_id": "CUST1013", "amount": 60.00, "currency": "EUR"},
    {"transaction_id": "TX1014", "customer_id": "CUST1014", "amount": 25.00, "currency": "YER"},
    {"transaction_id": "TX2001", "customer_id": "CUST1005", "amount": 9999.00, "currency": "EUR"},
    {"transaction_id": "TX2002", "customer_id": "CUST1005", "amount": 9998.00, "currency": "EUR"},
    {"transaction_id": "TX2003", "customer_id": "CUST1005", "amount": 9997.00, "currency": "EUR"},
]


@dataclass
class TransactionResult:
    """Result of a single transaction processing."""
    transaction_id: str
    customer_id: str
    amount: float
    currency: str
    risk_score: int = 0
    risk_level: str = "UNKNOWN"
    alert_created: bool = False
    alert_severity: str = "NONE"
    processing_time: float = 0.0
    status: str = "PENDING"
    error_message: Optional[str] = None


@dataclass
class BatchRunSummary:
    """Summary statistics for a batch run."""
    total_transactions: int = 0
    successful: int = 0
    failed: int = 0
    alerts_created: int = 0
    total_amount_processed: float = 0.0
    total_amount_blocked: float = 0.0
    avg_processing_time: float = 0.0
    avg_risk_score: float = 0.0
    risk_distribution: dict = field(default_factory=dict)
    alert_severity_distribution: dict = field(default_factory=dict)
    results: list = field(default_factory=list)


async def process_single_transaction(
    transaction: dict,
    telemetry_manager,
) -> TransactionResult:
    """
    Process a single transaction through the fraud detection workflow.
    
    Args:
        transaction: Transaction data dict with transaction_id, customer_id, amount, currency
        telemetry_manager: The telemetry manager for creating spans
        
    Returns:
        TransactionResult with the outcome
    """
    result = TransactionResult(
        transaction_id=transaction["transaction_id"],
        customer_id=transaction["customer_id"],
        amount=transaction["amount"],
        currency=transaction["currency"],
    )
    
    start_time = time.time()
    
    try:
        with telemetry_manager.create_workflow_span(
            "batch_transaction_processing",
            batch_processing=True,
            transaction_id=transaction["transaction_id"],
            customer_id=transaction["customer_id"],
            amount=transaction["amount"],
            currency=transaction["currency"],
        ) as span:
            span.add_event("Starting batch transaction processing")
            
            workflow_result = await run_fraud_detection_workflow(
                transaction_id=transaction["transaction_id"],
                customer_id=transaction["customer_id"],
                amount=transaction["amount"],
                currency=transaction["currency"],
            )
            
            if workflow_result:
                result.status = workflow_result.workflow_status
                result.alert_created = workflow_result.alert_created
                
                # Get risk info directly from workflow result
                result.risk_score = workflow_result.risk_score
                result.risk_level = workflow_result.risk_level
                
                # Determine alert severity
                if result.alert_created:
                    if result.risk_score >= 90:
                        result.alert_severity = "CRITICAL"
                    elif result.risk_score >= 75:
                        result.alert_severity = "HIGH"
                    elif result.risk_score >= 50:
                        result.alert_severity = "MEDIUM"
                    else:
                        result.alert_severity = "LOW"
                
                span.set_attributes({
                    "batch.risk_score": result.risk_score,
                    "batch.risk_level": result.risk_level,
                    "batch.alert_created": result.alert_created,
                    "batch.alert_severity": result.alert_severity,
                })
                span.add_event("Batch transaction completed successfully")
            else:
                result.status = "NO_RESULT"
                span.add_event("No result from workflow")
                
    except Exception as e:
        result.status = "ERROR"
        result.error_message = str(e)
        print(f"❌ Error processing {result.transaction_id}: {e}")
    
    result.processing_time = time.time() - start_time
    return result


async def run_batch_simulation(
    num_transactions: int = 10,
    delay_between: float = 2.0,
    randomize_delay: bool = False,
    shuffle_transactions: bool = False,
) -> BatchRunSummary:
    """
    Run a batch simulation of multiple fraud detection workflows.
    
    Args:
        num_transactions: Number of transactions to process
        delay_between: Base delay between transactions (seconds)
        randomize_delay: If True, randomize delay between 0.5x and 1.5x
        shuffle_transactions: If True, randomize transaction order
        
    Returns:
        BatchRunSummary with statistics and results
    """
    # Initialize telemetry
    initialize_telemetry()
    telemetry = get_telemetry_manager()
    
    summary = BatchRunSummary()
    summary.total_transactions = num_transactions
    
    print(f"\n{'='*70}")
    print(f"🚀 BATCH FRAUD DETECTION SIMULATION")
    print(f"{'='*70}")
    print(f"📊 Transactions to process: {num_transactions}")
    print(f"⏱️  Base delay between transactions: {delay_between}s")
    print(f"🎲 Randomize delay: {randomize_delay}")
    print(f"🔀 Shuffle transactions: {shuffle_transactions}")
    print(f"{'='*70}\n")
    
    # Prepare transaction list
    transactions = []
    for i in range(num_transactions):
        tx = AVAILABLE_TRANSACTIONS[i % len(AVAILABLE_TRANSACTIONS)].copy()
        # Add variation to make each batch unique
        if i >= len(AVAILABLE_TRANSACTIONS):
            tx["transaction_id"] = f"{tx['transaction_id']}-{i // len(AVAILABLE_TRANSACTIONS)}"
        transactions.append(tx)
    
    if shuffle_transactions:
        random.shuffle(transactions)
    
    # Send batch start event
    send_business_event("fraud_detection.batch.started", {
        "num_transactions": num_transactions,
        "start_time": datetime.now().isoformat(),
    })
    
    batch_start_time = time.time()
    
    # Process each transaction
    for i, transaction in enumerate(transactions, 1):
        print(f"\n[{i}/{num_transactions}] Processing {transaction['transaction_id']} "
              f"(Customer: {transaction['customer_id']}, Amount: {transaction['amount']} {transaction['currency']})")
        
        result = await process_single_transaction(transaction, telemetry)
        summary.results.append(result)
        
        # Update counters
        if result.status == "SUCCESS":
            summary.successful += 1
        else:
            summary.failed += 1
        
        if result.alert_created:
            summary.alerts_created += 1
            summary.total_amount_blocked += result.amount
            
            # Track severity distribution
            severity = result.alert_severity
            summary.alert_severity_distribution[severity] = \
                summary.alert_severity_distribution.get(severity, 0) + 1
        
        # Track risk distribution
        level = result.risk_level
        summary.risk_distribution[level] = summary.risk_distribution.get(level, 0) + 1
        
        summary.total_amount_processed += result.amount
        
        # Print result
        status_icon = "✅" if result.status == "SUCCESS" else "❌"
        alert_icon = "🚨" if result.alert_created else "✓"
        print(f"   {status_icon} Status: {result.status} | "
              f"Risk: {result.risk_score} ({result.risk_level}) | "
              f"Alert: {alert_icon} {result.alert_severity if result.alert_created else 'None'} | "
              f"Time: {result.processing_time:.2f}s")
        
        # Delay before next transaction
        if i < num_transactions:
            delay = delay_between
            if randomize_delay:
                delay = delay * random.uniform(0.5, 1.5)
            await asyncio.sleep(delay)
    
    batch_end_time = time.time()
    total_batch_time = batch_end_time - batch_start_time
    
    # Calculate averages
    if summary.successful > 0:
        successful_results = [r for r in summary.results if r.status == "SUCCESS"]
        summary.avg_processing_time = sum(r.processing_time for r in successful_results) / len(successful_results)
        summary.avg_risk_score = sum(r.risk_score for r in successful_results) / len(successful_results)
    
    # Send batch completed event
    send_business_event("fraud_detection.batch.completed", {
        "num_transactions": num_transactions,
        "successful": summary.successful,
        "failed": summary.failed,
        "alerts_created": summary.alerts_created,
        "total_amount_processed": summary.total_amount_processed,
        "total_amount_blocked": summary.total_amount_blocked,
        "avg_processing_time": summary.avg_processing_time,
        "avg_risk_score": summary.avg_risk_score,
        "total_batch_time": total_batch_time,
    })
    
    # Print summary
    print_batch_summary(summary, total_batch_time)
    
    # Flush telemetry to ensure all data is sent to Application Insights
    flush_telemetry()
    
    return summary


def print_batch_summary(summary: BatchRunSummary, total_batch_time: float):
    """Print a formatted summary of the batch run."""
    print(f"\n{'='*70}")
    print(f"📊 BATCH RUN SUMMARY")
    print(f"{'='*70}")
    
    success_rate = (summary.successful / summary.total_transactions * 100) if summary.total_transactions > 0 else 0
    alert_rate = (summary.alerts_created / summary.total_transactions * 100) if summary.total_transactions > 0 else 0
    
    print(f"\n📈 Overall Statistics:")
    print(f"   Total Transactions:     {summary.total_transactions}")
    print(f"   Successful:             {summary.successful} ({success_rate:.1f}%)")
    print(f"   Failed:                 {summary.failed}")
    print(f"   Total Batch Time:       {total_batch_time:.2f}s")
    print(f"   Avg Processing Time:    {summary.avg_processing_time:.2f}s")
    
    print(f"\n💰 Financial Impact:")
    print(f"   Total Amount Processed: ${summary.total_amount_processed:,.2f}")
    print(f"   Total Amount Blocked:   ${summary.total_amount_blocked:,.2f}")
    
    print(f"\n⚠️  Risk Analysis:")
    print(f"   Average Risk Score:     {summary.avg_risk_score:.1f}")
    print(f"   Risk Distribution:")
    for level in ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]:
        count = summary.risk_distribution.get(level, 0)
        pct = (count / summary.total_transactions * 100) if summary.total_transactions > 0 else 0
        bar = "█" * int(pct / 5)
        print(f"      {level:8} {count:3} ({pct:5.1f}%) {bar}")
    
    print(f"\n🚨 Alerts:")
    print(f"   Total Alerts Created:   {summary.alerts_created} ({alert_rate:.1f}%)")
    if summary.alerts_created > 0:
        print(f"   Severity Distribution:")
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = summary.alert_severity_distribution.get(severity, 0)
            pct = (count / summary.alerts_created * 100) if summary.alerts_created > 0 else 0
            print(f"      {severity:8} {count:3} ({pct:5.1f}%)")
    
    print(f"\n{'='*70}")


async def cleanup():
    """Clean up resources after batch run."""
    global _project_client, _credential
    from workflows.workflow import _project_client, _credential
    
    if _project_client:
        await _project_client.close()
    if _credential:
        await _credential.close()


# Preset simulation modes
async def quick_demo():
    """Quick demo with 5 transactions."""
    print("\n🎯 QUICK DEMO MODE (5 transactions)")
    summary = await run_batch_simulation(
        num_transactions=5,
        delay_between=1.0,
        randomize_delay=False,
    )
    await cleanup()
    return summary


async def stress_test():
    """Stress test with 20 transactions processed quickly."""
    print("\n💪 STRESS TEST MODE (20 transactions)")
    summary = await run_batch_simulation(
        num_transactions=20,
        delay_between=0.5,
        randomize_delay=False,
        shuffle_transactions=True,
    )
    await cleanup()
    return summary


async def business_day_simulation():
    """Simulate a business day with 50 transactions and random delays."""
    print("\n🏢 BUSINESS DAY SIMULATION (50 transactions)")
    summary = await run_batch_simulation(
        num_transactions=50,
        delay_between=3.0,
        randomize_delay=True,
        shuffle_transactions=True,
    )
    await cleanup()
    return summary


async def custom_run(num_transactions: int, delay: float = 2.0):
    """Custom run with specified number of transactions."""
    print(f"\n⚙️  CUSTOM RUN ({num_transactions} transactions)")
    summary = await run_batch_simulation(
        num_transactions=num_transactions,
        delay_between=delay,
        randomize_delay=True,
        shuffle_transactions=True,
    )
    await cleanup()
    return summary
