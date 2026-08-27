from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).parents[1] / "benchmarks" / "benchmark_simple_objects.py"
_SPEC = importlib.util.spec_from_file_location("benchmark_simple_objects", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_BENCHMARK = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BENCHMARK)


def test_history_keeps_at_most_fifty_states() -> None:
    history: list[bytes] = []
    for index in range(75):
        assert _BENCHMARK._bounded_history_append(history, str(index).encode())

    assert len(history) == 50
    assert history[0] == b"25"
    assert history[-1] == b"74"


def test_history_eviction_obeys_byte_limit() -> None:
    history: list[bytes] = []
    for index in range(10):
        assert _BENCHMARK._bounded_history_append(
            history, bytes([index]) * 4, max_states=50, max_bytes=10
        )

    assert len(history) == 2
    assert sum(map(len, history)) == 8
    assert history == [bytes([8]) * 4, bytes([9]) * 4]


def test_oversized_snapshot_is_rejected_without_mutating_history() -> None:
    history = [b"existing"]

    assert not _BENCHMARK._bounded_history_append(
        history, b"too-large", max_states=50, max_bytes=4
    )
    assert history == [b"existing"]


@pytest.mark.parametrize("max_states,max_bytes", [(0, 10), (10, 0), (-1, 10)])
def test_history_limits_must_be_positive(max_states: int, max_bytes: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        _BENCHMARK._bounded_history_append(
            [], b"snapshot", max_states=max_states, max_bytes=max_bytes
        )


def test_history_case_reports_contract_limits() -> None:
    result = _BENCHMARK._run_history_case(
        object_count=2,
        repetitions=2,
        max_states=50,
        max_bytes=64 * 1024 * 1024,
    )

    assert result["requested_states"] == 51
    assert result["retained_states"] == 50
    assert result["history_state_limit"] == 50
    assert result["history_byte_limit"] == 64 * 1024 * 1024
    assert result["history_bytes"] <= result["history_byte_limit"]
