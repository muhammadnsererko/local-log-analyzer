"""Two-stage local log anomaly analysis with confidence-based escalation."""

from __future__ import annotations

import json
import time
import threading
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

REPORT_PATH = Path(__file__).with_name("anomaly_report.jsonl")
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "qwen2.5:1.5b"


def load_and_train(logs: list[dict]) -> tuple[IsolationForest, StandardScaler]:
    """Fit a StandardScaler and IsolationForest on the numeric log features."""
    feature_rows: list[list[float]] = []
    for log in logs:
        feature_rows.append(
            [
                float(log["response_time_ms"]),
                float(log["status_code"]),
                float(log["cpu_percent"]),
                float(log["memory_percent"]),
                float(log["error_count"]),
            ]
        )

    features = np.array(feature_rows, dtype=float)
    scaler = StandardScaler()
    scaled_features = scaler.fit_transform(features)

    model = IsolationForest(contamination=0.01, n_estimators=50, random_state=42)
    training_start = time.perf_counter()
    model.fit(scaled_features)
    training_time_ms = (time.perf_counter() - training_start) * 1000
    print(f"Isolation Forest training time: {training_time_ms:.2f} ms")
    return model, scaler


def classify_confidence(score: float) -> str:
    """Convert a raw anomaly score into a readable confidence label."""
    if score < -0.22:
        return "HIGH"
    if -0.22 <= score <= -0.16:
        return "MEDIUM"
    return "LOW"


def detect_anomalies(model: IsolationForest, scaler: StandardScaler, logs: list[dict]) -> list[dict]:
    """Detect anomalies, attach raw scores, and label each anomaly with confidence."""
    feature_rows: list[list[float]] = []
    for log in logs:
        feature_rows.append(
            [
                float(log["response_time_ms"]),
                float(log["status_code"]),
                float(log["cpu_percent"]),
                float(log["memory_percent"]),
                float(log["error_count"]),
            ]
        )

    scaled_features = scaler.transform(np.array(feature_rows, dtype=float))
    predictions = model.predict(scaled_features)
    raw_scores = model.decision_function(scaled_features)

    anomalies: list[dict] = []
    flagged_scores = []
    for log, prediction, raw_score in zip(logs, predictions, raw_scores):
        if prediction == -1:
            score = float(raw_score)
            flagged_scores.append(score)
            confidence = classify_confidence(score)
            anomalies.append(
                {
                    "log_data": log,
                    "anomaly_score": score,
                    "confidence": confidence,
                    "escalate": confidence in {"HIGH", "MEDIUM"},
                }
            )

    if flagged_scores:
        print(
            "Flagged anomaly scores -> min: "
            f"{min(flagged_scores):.4f}, max: {max(flagged_scores):.4f}, mean: {np.mean(flagged_scores):.4f}"
        )
    else:
        print("Flagged anomaly scores -> no anomalies detected")

    return anomalies


def get_llm_summary(log_dict: dict) -> tuple[str, bool]:
    """Call the local Ollama model and request a two-sentence anomaly summary.

    Returns a tuple `(summary, success)`. `success` is False if the request
    timed out or failed, in which case `summary` will be a fallback message.
    """
    prompt = (
        "You are analyzing a system log anomaly. "
        "Using the full log dictionary provided, write exactly 2 sentences: "
        "the first sentence should explain what the anomaly indicates, and the second "
        "sentence should describe what should be investigated. "
        f"Log: {json.dumps(log_dict, sort_keys=True)}"
    )

    payload = {"model": MODEL_NAME, "prompt": prompt, "stream": False}
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    result: dict[str, object] = {"response_data": None, "error": None}

    def do_request():
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result["response_data"] = json.load(response)
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=do_request, daemon=True)
    thread.start()
    thread.join(timeout=120)

    if thread.is_alive():
        # Timed out; do not wait longer
        return (
            "The anomaly could not be summarized within the timeout. Investigate the related service telemetry and logs.",
            False,
        )

    if result.get("error") is not None:
        return (
            "The anomaly could not be summarized automatically. Investigate the related service telemetry and logs.",
            False,
        )

    response_data = result.get("response_data") or {}
    summary = str(response_data.get("response", "")).strip()
    if not summary:
        return (
            "The anomaly could not be summarized automatically. Investigate the related service telemetry and logs.",
            False,
        )
    return summary, True


def build_service_breakdown(anomalies: list[dict]) -> dict[str, Any]:
    """Group anomalies by service and identify the most affected service."""
    service_counts: dict[str, int] = {}
    for anomaly in anomalies:
        service = str(anomaly["log_data"].get("service", "unknown"))
        service_counts[service] = service_counts.get(service, 0) + 1

    if not service_counts:
        return {"by_service": {}, "top_service": "none", "top_service_count": 0}

    top_service, top_count = max(service_counts.items(), key=lambda item: item[1])
    return {
        "by_service": service_counts,
        "top_service": top_service,
        "top_service_count": top_count,
    }


def print_performance_dashboard(metrics: dict[str, Any]) -> None:
    """Print a concise performance dashboard for the pipeline."""
    print("\nPerformance dashboard")
    print(f"Stage 1 throughput: {metrics['stage1_throughput']:.2f} logs/sec")
    print(f"Stage 2 escalation rate: {metrics['escalation_rate']:.2f}%")
    print(f"Average LLM response time: {metrics['average_llm_response_time_ms']:.2f} ms/anomaly")
    print(f"LLM calls saved: {metrics['llm_calls_saved']}")
    service_breakdown = metrics["service_breakdown"]
    print(
        "Most affected service: "
        f"{service_breakdown['top_service']} ({service_breakdown['top_service_count']} anomalies)"
    )


def run_pipeline(logs: list[dict]) -> dict[str, Any]:
    """Run the full anomaly detection and summarization pipeline and write the report."""
    stage1_start = time.perf_counter()
    model, scaler = load_and_train(logs)
    anomalies = detect_anomalies(model, scaler, logs)
    stage1_elapsed_seconds = time.perf_counter() - stage1_start
    stage1_time_ms = stage1_elapsed_seconds * 1000

    stage1_throughput = len(logs) / stage1_elapsed_seconds if stage1_elapsed_seconds > 0 else float("inf")

    if REPORT_PATH.exists():
        REPORT_PATH.unlink()

    stage2_start = time.perf_counter()
    llm_response_times_ms: list[float] = []
    llm_failed_count = 0

    with REPORT_PATH.open("w", encoding="utf-8") as report_file:
        for index, anomaly in enumerate(anomalies, start=1):
            report_entry: dict[str, Any] = {
                "timestamp": anomaly["log_data"]["timestamp"],
                "service": anomaly["log_data"]["service"],
                "level": anomaly["log_data"]["level"],
                "anomaly_score": anomaly["anomaly_score"],
                "confidence": anomaly["confidence"],
                "log_data": anomaly["log_data"],
                "escalated_to_llm": anomaly["escalate"],
                "llm_summary": None,
            }

            # Diagnostic: print the anomaly's score, confidence, and service
            print(
                f"[anomaly {index}] score={anomaly['anomaly_score']:.4f} confidence={anomaly['confidence']} service={anomaly['log_data']['service']}"
            )

            if anomaly["escalate"]:
                llm_start = time.perf_counter()
                summary, success = get_llm_summary(anomaly["log_data"])
                llm_elapsed_ms = (time.perf_counter() - llm_start) * 1000
                if success:
                    llm_response_times_ms.append(llm_elapsed_ms)
                    report_entry["llm_summary"] = summary
                else:
                    llm_failed_count += 1
                    report_entry["llm_summary"] = None
                    report_entry["llm_failed"] = True

            report_file.write(json.dumps(report_entry, sort_keys=True) + "\n")
            if index % 10 == 0 or index == len(anomalies):
                print(f"Processed {index}/{len(anomalies)} anomalies")

    stage2_elapsed_seconds = time.perf_counter() - stage2_start
    service_breakdown = build_service_breakdown(anomalies)

    metrics: dict[str, Any] = {
        "stage1_time_ms": stage1_time_ms,
        "stage2_time_seconds": stage2_elapsed_seconds,
        "stage1_throughput": stage1_throughput,
        "anomalies_detected": len(anomalies),
        "llm_summaries_written": len(llm_response_times_ms),
        "llm_failed": llm_failed_count,
        "llm_calls_saved": max(0, len(anomalies) - (len(llm_response_times_ms) + llm_failed_count)),
        "escalation_rate": ((len(llm_response_times_ms) + llm_failed_count) / len(anomalies) * 100) if anomalies else 0.0,
        "average_llm_response_time_ms": (
            sum(llm_response_times_ms) / len(llm_response_times_ms) if llm_response_times_ms else 0.0
        ),
        "service_breakdown": service_breakdown,
        "report_path": str(REPORT_PATH),
    }

    print_performance_dashboard(metrics)
    return metrics
