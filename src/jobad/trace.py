"""Append-only JSONL trace of every LLM call in a run.

One line per call: step, model, tokens, latency, estimated cost, and the
validated output (or the error). This is what `jobad trace <run_id>` reads.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import LIST_PRICES


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    inp, out = LIST_PRICES.get(model, (0.0, 0.0))
    return round((prompt_tokens * inp + completion_tokens * out) / 1_000_000, 6)


@dataclass
class Tracer:
    run_id: str
    path: Path
    records: list[dict[str, Any]] = field(default_factory=list)

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
        rec = {
            "ts": time.time(),
            "run_id": self.run_id,
            "step": step,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_s": round(latency_s, 3),
            "est_cost_usd": estimate_cost(model, prompt_tokens, completion_tokens),
            "ok": ok,
            "attempt": attempt,
            "output": output,
            "error": error,
            "meta": meta or {},
        }
        self.records.append(rec)
        with self.path.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    @staticmethod
    def load(path: Path) -> list[dict[str, Any]]:
        with path.open() as f:
            return [json.loads(line) for line in f if line.strip()]

    @staticmethod
    def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
        by_step: dict[str, dict[str, Any]] = {}
        for r in records:
            s = by_step.setdefault(
                r["step"], {"calls": 0, "failures": 0, "prompt_tokens": 0, "completion_tokens": 0, "latency_s": 0.0, "est_cost_usd": 0.0, "models": set()}
            )
            s["calls"] += 1
            s["failures"] += 0 if r["ok"] else 1
            s["prompt_tokens"] += r["prompt_tokens"]
            s["completion_tokens"] += r["completion_tokens"]
            s["latency_s"] += r["latency_s"]
            s["est_cost_usd"] += r["est_cost_usd"]
            s["models"].add(r["model"])
        total = {
            "calls": sum(s["calls"] for s in by_step.values()),
            "failures": sum(s["failures"] for s in by_step.values()),
            "prompt_tokens": sum(s["prompt_tokens"] for s in by_step.values()),
            "completion_tokens": sum(s["completion_tokens"] for s in by_step.values()),
            "latency_s": round(sum(s["latency_s"] for s in by_step.values()), 2),
            "est_cost_usd": round(sum(s["est_cost_usd"] for s in by_step.values()), 5),
        }
        for s in by_step.values():
            s["models"] = sorted(s["models"])
            s["latency_s"] = round(s["latency_s"], 2)
            s["est_cost_usd"] = round(s["est_cost_usd"], 5)
        return {"by_step": by_step, "total": total}
