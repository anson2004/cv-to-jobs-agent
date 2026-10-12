"""Step 7a: pick top-k with a diversity rule. No LLM.

Rule: at most 2 jobs per company, at most 2 sharing a title stem. The point
is to avoid four near-identical recommendations, which a pure sort produces.
"""

from __future__ import annotations

from collections import Counter

from ..schemas import Job, JobScore
from ..textutil import norm_key, title_stem

MAX_PER_COMPANY = 2
MAX_PER_STEM = 2


def select_top(jobs: list[Job], scores: list[JobScore], k: int) -> list[tuple[Job, JobScore]]:
    by_id = {j.id: j for j in jobs}
    ranked = sorted((s for s in scores if s.job_id in by_id), key=lambda s: s.overall, reverse=True)
    companies: Counter = Counter()
    stems: Counter = Counter()
    out: list[tuple[Job, JobScore]] = []
    for s in ranked:
        j = by_id[s.job_id]
        c, st = norm_key(j.company), title_stem(j.title)
        if companies[c] >= MAX_PER_COMPANY or stems[st] >= MAX_PER_STEM:
            continue
        companies[c] += 1
        stems[st] += 1
        out.append((j, s))
        if len(out) == k:
            break
    return out
