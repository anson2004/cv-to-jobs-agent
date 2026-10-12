"""Step 10: evaluate the scorer against hand-labelled jobs.

labels.jsonl: one line per job, {"job_id": ..., "label": "good"|"ok"|"bad", "note": ...}
Metric: precision@k (how many of the scorer's top-k are labelled good),
mean overall per label, and the number of 'bad' jobs in the top-k. Results
are saved so prompt versions and models can be compared side by side.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import Settings
from .cv import cv_to_text
from .llm import LLM
from .pipeline.extract import extract_profile
from .pipeline.score import score_jobs
from .schemas import CandidateProfile, Job
from .store import Store
from .trace import Tracer

LABEL_ORDER = {"good": 2, "ok": 1, "bad": 0}


def export_candidates(settings: Settings, out: Path, limit: int = 60) -> int:
    """Dump jobs from the store so a human can label them."""
    store = Store(settings.db_path)
    jobs = store.all_jobs()[:limit]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for j in jobs:
            f.write(json.dumps({"job_id": j.id, "title": j.title, "company": j.company, "location": j.location, "remote": j.remote, "url": j.url, "snippet": j.description[:400]}) + "\n")
    return len(jobs)


def load_labels(path: Path) -> dict[str, dict]:
    with path.open() as f:
        rows = [json.loads(l) for l in f if l.strip()]
    return {r["job_id"]: r for r in rows}


def _profile(settings: Settings, llm: LLM, cv_path: Path, cache: Path) -> CandidateProfile:
    if cache.exists():
        return CandidateProfile.model_validate_json(cache.read_text())
    p = extract_profile(llm, cv_to_text(cv_path), settings.model_strong)
    cache.write_text(p.model_dump_json(indent=1))
    return p


def run_eval(settings: Settings, cv_path: Path, labels_path: Path, *, prompt_version: str, model: str, k: int = 4) -> dict:
    labels = load_labels(labels_path)
    store = Store(settings.db_path)
    jobs: list[Job] = [j for jid in labels if (j := store.get_job(jid)) is not None]
    missing = set(labels) - {j.id for j in jobs}
    if missing:
        print(f"  ! {len(missing)} labelled jobs not in store (run `jobad run` first): {sorted(missing)[:3]}…")

    run_id = f"eval-{prompt_version}-{model.split('/')[-1]}-{time.strftime('%H%M%S')}"
    tracer = Tracer.for_run(run_id, settings.traces_dir)
    llm = LLM(settings, tracer)
    profile = _profile(settings, llm, cv_path, labels_path.parent / "profile.json")

    scores = score_jobs(llm, profile, jobs, model=model, prompt_version=prompt_version, concurrency=settings.score_concurrency, chars=settings.description_chars)
    by_id = {s.job_id: s for s in scores}
    ranked = sorted(scores, key=lambda s: s.overall, reverse=True)
    topk = ranked[:k]

    def mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    per_label = {lab: mean([by_id[j].overall for j in labels if j in by_id and labels[j]["label"] == lab]) for lab in LABEL_ORDER}
    n_good = sum(1 for lab in labels.values() if lab["label"] == "good")
    result = {
        "prompt_version": prompt_version,
        "model": model,
        "n_labelled": len(labels),
        "n_scored": len(scores),
        "k": k,
        "precision_at_k": round(sum(1 for s in topk if labels[s.job_id]["label"] == "good") / k, 2),
        "bad_in_top_k": sum(1 for s in topk if labels[s.job_id]["label"] == "bad"),
        "recall_at_k": round(sum(1 for s in topk if labels[s.job_id]["label"] == "good") / max(n_good, 1), 2),
        "mean_overall_by_label": per_label,
        "separation": round((per_label["good"] or 0) - (per_label["bad"] or 0), 2),
        "top_k": [{"job_id": s.job_id, "overall": s.overall, "label": labels[s.job_id]["label"]} for s in topk],
        "usage": tracer.summarize(tracer.records)["total"],
        "trace": str(tracer.path),
    }
    results_dir = labels_path.parent / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / f"{prompt_version}_{model.split('/')[-1]}.json").write_text(json.dumps(result, indent=1))
    return result


def load_results(labels_path: Path) -> list[dict]:
    d = labels_path.parent / "results"
    if not d.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]
