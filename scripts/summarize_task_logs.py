#!/usr/bin/env python3
"""Summarize Celery task lifecycle JSONL logs into CSV or JSON statistics."""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


FIELDS = (
    "task_name",
    "completed",
    "succeeded",
    "failed",
    "retried",
    "avg_runtime_seconds",
    "p50_runtime_seconds",
    "p95_runtime_seconds",
    "max_runtime_seconds",
)


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 6)


def collect_summaries(logs_dir):
    stats = defaultdict(lambda: {"states": defaultdict(int), "runtimes": []})
    for path in sorted(logs_dir.glob("celery-worker.jsonl*")):
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8") as log_file:
                for line_number, line in enumerate(log_file, start=1):
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        print(f"Skipping invalid JSON: {path}:{line_number}", file=sys.stderr)
                        continue
                    if record.get("event_type") != "celery_task_finished":
                        continue
                    task_name = record.get("task_name")
                    if not task_name:
                        continue
                    task_stats = stats[task_name]
                    task_stats["states"][record.get("task_state", "UNKNOWN")] += 1
                    runtime = record.get("runtime_seconds")
                    if isinstance(runtime, (int, float)):
                        task_stats["runtimes"].append(float(runtime))
        except OSError as error:
            print(f"Could not read {path}: {error}", file=sys.stderr)

    summaries = []
    for task_name, task_stats in sorted(stats.items()):
        states = task_stats["states"]
        runtimes = task_stats["runtimes"]
        completed = sum(states.values())
        summaries.append(
            {
                "task_name": task_name,
                "completed": completed,
                "succeeded": states["SUCCESS"],
                "failed": states["FAILURE"],
                "retried": states["RETRY"],
                "avg_runtime_seconds": round(sum(runtimes) / len(runtimes), 6) if runtimes else None,
                "p50_runtime_seconds": percentile(runtimes, 0.50),
                "p95_runtime_seconds": percentile(runtimes, 0.95),
                "max_runtime_seconds": round(max(runtimes), 6) if runtimes else None,
            }
        )
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"), help="Directory containing Celery JSONL logs")
    parser.add_argument("--format", choices=("csv", "json"), default="csv", help="Output format (default: csv)")
    args = parser.parse_args()

    summaries = collect_summaries(args.logs_dir)
    if args.format == "json":
        json.dump(summaries, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(summaries)


if __name__ == "__main__":
    main()
