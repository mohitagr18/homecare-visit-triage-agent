"""Pure metric functions — no side effects, fully unit-testable.

Each function returns 0.0 or 1.0 (binary scoring).
Tolerance units are always MINUTES.
"""

from __future__ import annotations

import datetime
from typing import Any


def hours_match(predicted: float, expected: float, tolerance_minutes: int) -> float:
    """Return 1.0 if |predicted - expected| <= tolerance_minutes/60, else 0.0.

    Args:
        predicted: Extracted total hours (e.g. 7.25).
        expected:  Ground-truth total hours (e.g. 7.0).
        tolerance_minutes: Allowed delta in minutes (e.g. 15 for ±15min).

    Examples:
        >>> hours_match(7.0, 7.25, 15)   # 0.25h = 15min → boundary pass
        1.0
        >>> hours_match(7.0, 7.26, 15)   # 0.26h > 15min → fail
        0.0
    """
    tolerance_hours = tolerance_minutes / 60.0
    return 1.0 if abs(predicted - expected) <= tolerance_hours else 0.0


def time_match(
    predicted: datetime.time, expected: datetime.time, tolerance_minutes: int
) -> float:
    """Return 1.0 if |predicted - expected| <= tolerance_minutes, else 0.0.

    Converts both times to minutes-since-midnight for comparison.
    Does not handle overnight shifts (midnight crossing) — not needed for this dataset.

    Args:
        predicted: Extracted time (e.g. time(8, 30)).
        expected:  Ground-truth time (e.g. time(8, 45)).
        tolerance_minutes: Allowed delta in minutes (e.g. 30 for ±30min).

    Examples:
        >>> time_match(time(8, 30), time(8, 45), 30)   # 15min diff → pass
        1.0
        >>> time_match(time(8, 30), time(9, 15), 30)   # 45min diff → fail
        0.0
    """
    pred_min = predicted.hour * 60 + predicted.minute
    exp_min = expected.hour * 60 + expected.minute
    return 1.0 if abs(pred_min - exp_min) <= tolerance_minutes else 0.0


def exact_match(a: Any, b: Any) -> float:
    """Return 1.0 if a == b (with None handling), else 0.0."""
    if a is None and b is None:
        return 1.0
    if a is None or b is None:
        return 0.0
    return 1.0 if a == b else 0.0
