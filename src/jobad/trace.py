"""Append-only JSONL trace of every LLM call in a run.

One line per call: step, model, tokens, latency, estimated cost, and the
validated output (or the error). This is what `jobad trace <run_id>` reads.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .config import LIST_PRICES

_lock = threading.Lock()


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    inp, out = LIST_PRICES.get(model, (0.0, 0.0))
    return round((prompt_tokens * inp + completion_tokens * out) / 1_000_000, 6)


class TraceRecord(BaseModel):
    """One line of a trace file."""

    ts: float
    run_id: str
    step: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    est_cost_usd: float
    ok: bool
    attempt: int
    output: Any = None
    error: str | None = None
    meta: dict[str, Any] = {}


class Usage(BaseModel):
    calls: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    est_cost_usd: float = 0.0


class StepUsage(Usage):
    models: list[str] = []


class TraceSummary(BaseModel):
    by_step: dict[str, StepUsage]
    total: Usage


@dataclass
class Tracer:
    run_id: str
    path: Path
    records: list[TraceRecord] = field(default_factory=list)

    @classmethod
    def for_run(cls, run_id: str, traces_dir: Path) -> "Tracer":
        traces_dir.mkdir(parents=True, exist_ok=True)
        return cls(run_id=run_id, path=traces_dir / f"{run_id}.jsonl")

    def record(
        self,
        *,
        step: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_s: float,
        ok: bool,
        attempt: int,
        output: Any = None,
        error: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        rec = TraceRecord(
            ts=time.time(),
            run_id=self.run_id,
            step=step,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_s=round(latency_s, 3),
            est_cost_usd=estimate_cost(model, prompt_tokens, completion_tokens),
            ok=ok,
            attempt=attempt,
            output=output,
            error=error,
            meta=meta or {},
        )
        with _lock:  # search workers run in threads
            self.records.append(rec)
            with self.path.open("a") as f:
                f.write(rec.model_dump_json(fallback=str) + "\n")

    @staticmethod
    def load(path: Path) -> list[TraceRecord]:
        with path.open() as f:
            return [TraceRecord.model_validate_json(line) for line in f if line.strip()]

    @staticmethod
    def summarize(records: list[TraceRecord]) -> TraceSummary:
        by_step: dict[str, StepUsage] = {}
        models: dict[str, set[str]] = {}
        for r in records:
            s = by_step.setdefault(r.step, StepUsage())
            s.calls += 1
            s.failures += 0 if r.ok else 1
            s.prompt_tokens += r.prompt_tokens
            s.completion_tokens += r.completion_tokens
            s.latency_s += r.latency_s
            s.est_cost_usd += r.est_cost_usd
            models.setdefault(r.step, set()).add(r.model)
        total = Usage(
            calls=sum(s.calls for s in by_step.values()),
            failures=sum(s.failures for s in by_step.values()),
            prompt_tokens=sum(s.prompt_tokens for s in by_step.values()),
            completion_tokens=sum(s.completion_tokens for s in by_step.values()),
            latency_s=round(sum(s.latency_s for s in by_step.values()), 2),
            est_cost_usd=round(sum(s.est_cost_usd for s in by_step.values()), 5),
        )
        for step, s in by_step.items():
            s.models = sorted(models[step])
            s.latency_s = round(s.latency_s, 2)
            s.est_cost_usd = round(s.est_cost_usd, 5)
        return TraceSummary(by_step=by_step, total=total)
