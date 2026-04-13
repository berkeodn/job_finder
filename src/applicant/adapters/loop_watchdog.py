"""Detect repetitive agent actions across browser-use steps (any site, any tool).

- Optional hard-stop via ``should_stop_now()`` (pairs with Agent register_should_stop_callback).
- ``is_loop_pattern()``: read-only repetitive-behaviour check without mutating stop_reason.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, deque
from typing import Any

logger = logging.getLogger(__name__)


def _fingerprint_action(action: Any) -> str:
    try:
        data = action.model_dump(exclude_unset=True)
    except Exception:
        return f"unknown|{type(action).__name__}"
    if not data:
        return "empty"
    name = next(iter(data.keys()))
    params = data.get(name, {})
    if isinstance(params, dict):
        return f"{name}|{json.dumps(params, sort_keys=True, default=str)}"
    return f"{name}|{params!r}"


class ActionLoopWatchdog:
    """Tracks per-action fingerprints across steps; optional stop_reason for hard-stop mode."""

    def __init__(
        self,
        window_size: int = 24,
        max_identical_in_window: int = 6,
        max_consecutive_identical: int = 5,
    ) -> None:
        self._window_size = max(8, window_size)
        self._max_in_window = max(3, max_identical_in_window)
        self._max_consecutive = max(3, max_consecutive_identical)
        self._recent: deque[str] = deque(maxlen=self._window_size)
        self._consecutive = 0
        self._last_fp: str | None = None
        self.stop_reason: str | None = None
        self.recovery_mid_run_injected: bool = False

    def record_model_output(self, model_output: Any) -> None:
        """Call from register_new_step_callback after each LLM step."""
        if self.stop_reason:
            return
        if model_output is None:
            return
        actions = getattr(model_output, "action", None)
        if not actions:
            return
        for action in actions:
            fp = _fingerprint_action(action)
            self._record_fingerprint(fp)

    def _record_fingerprint(self, fp: str) -> None:
        self._recent.append(fp)
        if fp == self._last_fp:
            self._consecutive += 1
        else:
            self._last_fp = fp
            self._consecutive = 1

    def should_inject_mid_run_recovery(self, after_consecutive: int) -> bool:
        """True once when the same fingerprint repeated **more than** ``after_consecutive`` times.

        Example: ``after_consecutive=2`` → inject starting at the 3rd identical action in a row.
        """
        if self.recovery_mid_run_injected:
            return False
        return self._consecutive > after_consecutive

    def mark_mid_run_recovery_injected(self) -> None:
        self.recovery_mid_run_injected = True

    def is_loop_pattern(self) -> bool:
        """True if current fingerprints show repetitive behaviour (no side effects)."""
        if len(self._recent) < 3:
            return False
        if self._consecutive >= self._max_consecutive:
            return True
        counts = Counter(self._recent)
        _top, cnt = counts.most_common(1)[0]
        return cnt >= self._max_in_window

    def should_stop_now(self) -> bool:
        """Return True once when thresholds exceeded; sets stop_reason (hard-stop mode)."""
        if self.stop_reason:
            return True
        if not self.is_loop_pattern():
            return False
        if self._consecutive >= self._max_consecutive:
            fp_short = (self._last_fp or "")[:120]
            self.stop_reason = (
                f"same action fingerprint repeated {self._consecutive} times in a row "
                f"(threshold {self._max_consecutive}); last={fp_short!r}"
            )
        else:
            counts = Counter(self._recent)
            top, cnt = counts.most_common(1)[0]
            self.stop_reason = (
                f"one action appeared {cnt} times in the last {len(self._recent)} actions "
                f"(threshold {self._max_in_window}); fp={top[:120]!r}..."
            )
        logger.warning("Loop watchdog (hard stop): %s", self.stop_reason)
        return True
