"""Validated MCTS runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class MctsConfig:
    iterations: int = 200
    exploration_constant: float = 1.4
    max_rollout_depth: int = 20
    epsilon: float = 0.15
    time_budget_ms: int = 5000

    @classmethod
    def from_env(cls):
        return cls(
            iterations=_env_int("GCG_MCTS_ITERATIONS", 200, minimum=1, maximum=5000),
            exploration_constant=_env_float("GCG_MCTS_EXPLORATION_C", 1.4, minimum=0.0, maximum=10.0),
            max_rollout_depth=_env_int("GCG_MCTS_ROLLOUT_DEPTH", 20, minimum=1, maximum=200),
            epsilon=_env_float("GCG_MCTS_EPSILON", 0.15, minimum=0.0, maximum=1.0),
            time_budget_ms=_env_int("GCG_MCTS_TIME_BUDGET_MS", 5000, minimum=50, maximum=60000),
        )


def _env_int(name, default, minimum, maximum):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _env_float(name, default, minimum, maximum):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value
