"""Step 6: one LLM call per job, fast model, under a semaphore.

Descriptions are truncated to keep each call ~700-900 tokens, which matters on
an 8K tokens/minute free tier. Failed jobs are skipped, not fatal.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from ..llm import LLM
from ..prompts import load_prompt
from ..schemas import CandidateProfile, Job, JobScore
from ..textutil import truncate


def _profile_compact(p: CandidateProfile) -> str:
    return p.model_dump_json(include={"headline", "seniority", "years_experience", "skills", "locations_ok", "remote_ok", "must_haves", "dealbreakers"})


def _job_compact(j: Job, chars: int) -> str:
    return (
        f"job_id: {j.id}\ntitle: {j.title}\ncompany: {j.company}\nlocation: {j.location}\nremote: {j.remote}\n"
        f"tags: {', '.join(j.tags[:12])}\n\ndescription:\n{truncate(j.description, chars)}"
    )


async def _score_all(llm: LLM, profile: CandidateProfile, jobs: list[Job], model: str, prompt_version: str, concurrency: int, chars: int, on_done: Callable[[], None] | None = None) -> list[JobScore]:
    system = load_prompt(f"score_job_{prompt_version}")
    sem = asyncio.Semaphore(concurrency)
    pc = _profile_compact(profile)

    async def one(j: Job) -> JobScore | None:
        try:
            s = await llm.acomplete_json(
                JobScore,
                step="score_job",
                model=model,
                system=system,
                user=f"Candidate:\n{pc}\n\nJob:\n{_job_compact(j, chars)}\n\nUse job_id exactly as given.",
                reasoning_effort="low",
                max_tokens=700,
                meta={"job_id": j.id, "prompt_version": prompt_version},
                sem=sem,
            )
            s.job_id = j.id  # never trust the model with the key
            return s
        except Exception as e:
            print(f"  ! scoring failed for {j.id}: {type(e).__name__}: {str(e)[:120]}")
            llm.tracer.record(step="score_job", model=model, prompt_tokens=0, completion_tokens=0, latency_s=0.0, ok=False, attempt=0, error=f"{type(e).__name__}: {str(e)[:300]}", meta={"job_id": j.id, "prompt_version": prompt_version})
            return None
        finally:
            if on_done:
                on_done()

    results = await asyncio.gather(*(one(j) for j in jobs))
    return [r for r in results if r is not None]


def score_jobs(llm: LLM, profile: CandidateProfile, jobs: list[Job], *, model: str, prompt_version: str, concurrency: int, chars: int, on_done: Callable[[], None] | None = None) -> list[JobScore]:
    return asyncio.run(_score_all(llm, profile, jobs, model, prompt_version, concurrency, chars, on_done))
