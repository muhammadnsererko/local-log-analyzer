"""Run the local log anomaly analyzer from the command line."""

from __future__ import annotations

import time

from analyzer import run_pipeline
from log_generator import generate_log_stream


def main() -> None:
    """Generate logs, run the pipeline, and print a concise summary."""
    start = time.perf_counter()
    logs = generate_log_stream(1000)
    metrics = run_pipeline(logs)
    elapsed_seconds = time.perf_counter() - start

    print("\nSummary")
    print(f"Total logs processed: {len(logs)}")
    print(f"Anomalies detected by Stage 1: {metrics['anomalies_detected']}")
    print(f"Anomalies with LLM summaries written to report: {metrics['llm_summaries_written']}")
    print(f"Time taken for Stage 1 (ms): {metrics['stage1_time_ms']:.2f}")
    print(f"Time taken for Stage 2 (seconds): {metrics['stage2_time_seconds']:.2f}")
    print(f"Path to anomaly_report.jsonl: {metrics['report_path']}")
    print(f"Total runtime (seconds): {elapsed_seconds:.2f}")


if __name__ == "__main__":
    main()
