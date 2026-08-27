"""Baseline benchmark for creating and serializing simple Qt graphics items.

Run this file directly from the repository root.  It intentionally does not
exercise application code: M0 needs a stable Qt/Python baseline before feature
work makes the end-to-end scene path more complex.
"""

# ruff: noqa: I001

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PySide6
from PySide6 import QtCore, QtGui, QtWidgets


DEFAULT_COUNTS = (100, 1000, 2000)
DEFAULT_REPETITIONS = 20
DEFAULT_WARMUPS = 3
DEFAULT_HISTORY_STATES = 50
DEFAULT_HISTORY_BYTES = 64 * 1024 * 1024


def _simple_object_payload(index: int) -> dict[str, int | str]:
    """Return the deterministic JSON representation of one simple rectangle."""
    return {
        "type": "rect",
        "x": (index % 40) * 24,
        "y": (index // 40) * 18,
        "width": 20,
        "height": 14,
    }


def _build_and_serialize(object_count: int) -> tuple[int, int]:
    """Create native rectangles, flush Qt events, and serialize their state."""
    scene = QtWidgets.QGraphicsScene()
    payload = []
    for index in range(object_count):
        item = _simple_object_payload(index)
        scene.addItem(
            QtWidgets.QGraphicsRectItem(
                item["x"], item["y"], item["width"], item["height"]
            )
        )
        payload.append(item)

    QtWidgets.QApplication.processEvents()
    payload_bytes = len(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return len(scene.items()), payload_bytes


def _percentile(values: list[float], percentile: float) -> float:
    """Calculate an inclusive percentile so small samples remain meaningful."""
    if not values:
        raise ValueError("cannot calculate a percentile from no values")
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[percentile - 1]


def _runtime_metadata() -> dict[str, Any]:
    return {
        "python": sys.version,
        "python_implementation": platform.python_implementation(),
        "pyside6": PySide6.__version__,
        "qt": QtCore.qVersion(),
        "cpu": {
            "architecture": platform.machine(),
            "logical_cores": os.cpu_count(),
            "model": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER"),
        },
        "qt_platform": QtGui.QGuiApplication.platformName(),
    }


def _run_case(object_count: int, repetitions: int) -> dict[str, Any]:
    timings_ms: list[float] = []
    payload_bytes: int | None = None
    for _ in range(repetitions):
        start_ns = time.perf_counter_ns()
        created_items, current_payload_bytes = _build_and_serialize(object_count)
        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        if created_items != object_count:
            raise RuntimeError(f"expected {object_count} items, got {created_items}")
        if payload_bytes is None:
            payload_bytes = current_payload_bytes
        elif payload_bytes != current_payload_bytes:
            raise RuntimeError("deterministic JSON payload changed between repetitions")
        timings_ms.append(elapsed_ms)

    timings_ms.sort()
    return {
        "object_count": object_count,
        "json_payload_bytes": payload_bytes,
        "samples_ms": timings_ms,
        "median_ms": statistics.median(timings_ms),
        "p95_ms": _percentile(timings_ms, 95),
        "max_ms": max(timings_ms),
    }


def _bounded_history_append(
    history: list[bytes],
    payload: bytes,
    *,
    max_states: int = DEFAULT_HISTORY_STATES,
    max_bytes: int = DEFAULT_HISTORY_BYTES,
) -> bool:
    """Append one snapshot while enforcing both history limits."""
    if max_states < 1 or max_bytes < 1:
        raise ValueError("history limits must be positive")
    if len(payload) > max_bytes:
        return False
    history.append(payload)
    while len(history) > max_states or sum(map(len, history)) > max_bytes:
        history.pop(0)
    return True


def _history_snapshot(state_index: int, object_count: int) -> bytes:
    """Create a deterministic serialized snapshot for history measurements."""
    payload = {
        "state_index": state_index,
        "items": [_simple_object_payload(index) for index in range(object_count)],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _run_history_case(
    *,
    object_count: int,
    repetitions: int,
    max_states: int = DEFAULT_HISTORY_STATES,
    max_bytes: int = DEFAULT_HISTORY_BYTES,
) -> dict[str, Any]:
    """Measure bounded history growth and report both contract limits."""
    timings_ms: list[float] = []
    final_history: list[bytes] = []
    for _ in range(repetitions):
        history: list[bytes] = []
        start_ns = time.perf_counter_ns()
        for state_index in range(max_states + 1):
            _bounded_history_append(
                history,
                _history_snapshot(state_index, object_count),
                max_states=max_states,
                max_bytes=max_bytes,
            )
        timings_ms.append((time.perf_counter_ns() - start_ns) / 1_000_000)
        final_history = history

    total_bytes = sum(map(len, final_history))
    assert len(final_history) <= max_states
    assert total_bytes <= max_bytes
    timings_ms.sort()
    return {
        "object_count": object_count,
        "requested_states": max_states + 1,
        "retained_states": len(final_history),
        "history_bytes": total_bytes,
        "history_state_limit": max_states,
        "history_byte_limit": max_bytes,
        "samples_ms": timings_ms,
        "median_ms": statistics.median(timings_ms),
        "p95_ms": _percentile(timings_ms, 95),
        "max_ms": max(timings_ms),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=int, nargs="+", default=DEFAULT_COUNTS)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--history-states", type=int, default=DEFAULT_HISTORY_STATES)
    parser.add_argument("--history-bytes", type=int, default=DEFAULT_HISTORY_BYTES)
    parser.add_argument("--output", type=Path, help="Write the JSON report to this path.")
    args = parser.parse_args()
    if any(count <= 0 for count in args.counts):
        parser.error("--counts values must be positive")
    if args.repetitions < 2:
        parser.error("--repetitions must be at least 2")
    if args.warmups < 0:
        parser.error("--warmups must be zero or greater")
    if args.history_states < 1:
        parser.error("--history-states must be positive")
    if args.history_bytes < 1:
        parser.error("--history-bytes must be positive")
    return args


def main() -> int:
    args = _parse_args()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    del app  # Keep the application alive through this function without reconfiguring it.

    gc_enabled = gc.isenabled()
    gc.disable()
    try:
        for count in args.counts:
            for _ in range(args.warmups):
                _build_and_serialize(count)
        for _ in range(args.warmups):
            _run_history_case(
                object_count=max(args.counts),
                repetitions=args.repetitions,
                max_states=args.history_states,
                max_bytes=args.history_bytes,
            )
        report = {
            "schema_version": 1,
            "kind": "baseline-only",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "workload": {
                "operation": "create QGraphicsRectItem objects, flush Qt events, serialize JSON",
                "object_type": "QGraphicsRectItem",
                "counts": args.counts,
                "warmups_per_count": args.warmups,
                "repetitions_per_count": args.repetitions,
            },
            "runtime": _runtime_metadata(),
            "gates": {
                "status": "disabled-until-post-M0",
                "p95_ms_limit": 100,
                "max_ms_limit": 150,
                "reason": "M0 establishes the baseline; this benchmark never fails on these limits.",
            },
            "results": [_run_case(count, args.repetitions) for count in args.counts],
            "history_contract": {
                "operation": "serialize and retain one snapshot per history state",
                "state_limit": args.history_states,
                "byte_limit": args.history_bytes,
                "gates": "active",
                "result": _run_history_case(
                    object_count=max(args.counts),
                    repetitions=args.repetitions,
                    max_states=args.history_states,
                    max_bytes=args.history_bytes,
                ),
            },
        }
    finally:
        if gc_enabled:
            gc.enable()

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
