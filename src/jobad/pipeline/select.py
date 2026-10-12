"""Step 7a: pick top-k with a diversity rule and an optional local preference. No LLM.

Diversity: at most 2 jobs per company, at most 2 sharing a title stem, to avoid
four near-identical recommendations. Local preference: when a location filter
is set, postings physically in that place get a small bonus over remote ones,
so "limit to Tampere" ranks Tampere above remote-Europe on otherwise equal
scores. Both are product policy, so they live in code, not in the prompt.
"""

from __future__ import annotations

from collections import Counter

from ..schemas import Job, JobScore
from ..textutil import norm_key, title_stem
from .locate import wanted_terms

MAX_PER_COMPANY = 2
MAX_PER_STEM = 2
LOCAL_BONUS = 0.3  # on a 0-5 scale: breaks ties, does not override a clearly better remote job


def _is_local(job: Job, location: str | None) -> bool:
    if not location:
        return False
    import re

    words = {w.lower() for w in re.findall(r"[a-zäöå]+", job.location, re.I)}
    return bool(words & wanted_terms(location))


def select_top(jobs: list[Job], scores: list[JobScore], k: int, location: str | None = None) -> list[tuple[Job, JobScore]]:
    by_id = {j.id: j for j in jobs}

    def rank_key(s: JobScore) -> tuple[float, bool]:
        local = _is_local(by_id[s.job_id], location)
        return (round(s.overall + (LOCAL_BONUS if local else 0.0), 2), local)  # equal scores: local first

    ranked = sorted((s for s in scores if s.job_id in by_id), key=rank_key, reverse=True)
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
