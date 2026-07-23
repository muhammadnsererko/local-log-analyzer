"""Generate synthetic system logs for local anomaly analysis."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from faker import Faker

faker = Faker()
faker.seed_instance(42)
random.seed(42)

LEVELS = ["INFO", "WARNING", "ERROR", "CRITICAL"]
SERVICES = ["api-gateway", "auth-service", "payment-service", "database", "cache"]


def generate_log_stream(n: int = 1000) -> list[dict]:
    """Generate a synthetic stream of system logs with mixed anomaly severity.

    This function injects three tiers of anomalies randomly across the stream:
    - SEVERE (~0.4%): very large spikes
    - MODERATE (~0.4%): mid-level spikes
    - MILD (~0.2%): small but notable deviations
    """
    if n <= 0:
        raise ValueError("n must be positive")

    severe_count = max(1, round(n * 0.004))   # ~0.4%
    moderate_count = max(1, round(n * 0.004)) # ~0.4%
    mild_count = max(1, round(n * 0.002))     # ~0.2%

    # Randomly choose which indices will be anomalies so they are distributed
    indices = list(range(n))
    random.shuffle(indices)
    severe_indices = set(indices[0:severe_count])
    moderate_indices = set(indices[severe_count:severe_count + moderate_count])
    mild_indices = set(indices[severe_count + moderate_count:severe_count + moderate_count + mild_count])

    logs: list[dict] = []

    for index in range(n):
        base_time = datetime.now(timezone.utc) - timedelta(seconds=(n - index) * 2)

        # Base (normal) values
        log: dict[str, object] = {
            "timestamp": base_time.isoformat(),
            "level": random.choice(LEVELS),
            "service": random.choice(SERVICES),
            "response_time_ms": random.randint(50, 200),
            "status_code": random.choice([200, 201, 204]),
            "cpu_percent": random.randint(20, 60),
            "memory_percent": random.randint(30, 70),
            "error_count": 0,
        }

        if index in severe_indices:
            # SEVERE anomalies (~0.4%)
            log["timestamp"] = faker.iso8601(timespec="seconds")
            log["level"] = random.choice(["ERROR", "CRITICAL"])
            log["service"] = random.choice(["payment-service", "database", "cache"])
            log["response_time_ms"] = random.randint(8000, 15000)
            log["status_code"] = random.choice([503, 504])
            log["cpu_percent"] = random.randint(95, 100)
            log["memory_percent"] = random.randint(70, 90)
            log["error_count"] = random.randint(30, 50)

        elif index in moderate_indices:
            # MODERATE anomalies (~0.4%)
            log["timestamp"] = faker.iso8601(timespec="seconds")
            log["level"] = random.choice(["ERROR", "CRITICAL"])
            log["service"] = random.choice(["api-gateway", "payment-service", "auth-service"])
            log["response_time_ms"] = random.randint(2000, 4000)
            log["status_code"] = random.choice([500, 502])
            log["cpu_percent"] = random.randint(80, 90)
            log["memory_percent"] = random.randint(70, 85)
            log["error_count"] = random.randint(10, 20)

        elif index in mild_indices:
            # MILD anomalies (~0.2%)
            log["timestamp"] = faker.iso8601(timespec="seconds")
            log["level"] = random.choice(["WARNING", "ERROR"])
            log["service"] = random.choice(["api-gateway", "auth-service", "cache"])
            log["response_time_ms"] = random.randint(300, 600)
            log["status_code"] = 429
            log["cpu_percent"] = random.randint(65, 75)
            log["memory_percent"] = random.randint(72, 80)
            log["error_count"] = random.randint(1, 3)

        logs.append(log)

    return logs
