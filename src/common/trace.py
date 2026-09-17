"""Lightweight execution trace. The demo shows this panel live so the audience
can see intent -> router -> subagent -> tool call, not just the final answer."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-22s %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@dataclass
class TraceStep:
    stage: str
    detail: str
    payload: dict[str, Any] = field(default_factory=dict)
    ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "detail": self.detail,
            "payload": self.payload,
            "ms": round(self.ms, 1),
        }


class Trace:
    def __init__(self) -> None:
        self.steps: list[TraceStep] = []
        self._log = get_logger("trace")

    def step(self, stage: str, detail: str, **payload: Any) -> "TraceTimer":
        return TraceTimer(self, stage, detail, payload)

    def record(self, step: TraceStep) -> None:
        self.steps.append(step)
        self._log.info("[%s] %s (%.0f ms)", step.stage, step.detail, step.ms)

    def as_list(self) -> list[dict[str, Any]]:
        return [s.as_dict() for s in self.steps]


class TraceTimer:
    def __init__(self, trace: Trace, stage: str, detail: str, payload: dict[str, Any]) -> None:
        self._trace = trace
        self._step = TraceStep(stage=stage, detail=detail, payload=payload)

    def __enter__(self) -> TraceStep:
        self._t0 = time.perf_counter()
        return self._step

    def __exit__(self, *exc: object) -> None:
        self._step.ms = (time.perf_counter() - self._t0) * 1000
        self._trace.record(self._step)
