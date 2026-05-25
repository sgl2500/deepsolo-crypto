from __future__ import annotations

from dataclasses import dataclass

from cryptov2.live.broker import Broker
from cryptov2.live.state import JsonStateStore
from cryptov2.strategies.base import Strategy


@dataclass(slots=True)
class LiveRunnerConfig:
    dry_run: bool = True
    interval_seconds: int = 300


class LiveRunner:
    """Live orchestration skeleton. Real exchange trading is intentionally not implemented yet."""

    def __init__(self, strategy: Strategy, broker: Broker, state: JsonStateStore, config: LiveRunnerConfig):
        self.strategy = strategy
        self.broker = broker
        self.state = state
        self.config = config

    def healthcheck(self) -> dict:
        return {
            "strategy": self.strategy.name,
            "dry_run": self.config.dry_run,
            "positions": len(self.broker.positions()),
            "state_path": str(self.state.path),
        }
