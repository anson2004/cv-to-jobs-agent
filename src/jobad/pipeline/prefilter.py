"""Step 5b: cheap lexical prior to decide which jobs get the expensive model call.

The job APIs are keyword-matched loosely (Arbeitnow in particular returns many
unrelated postings for any query). Counting how many queries hit a job rewards
exactly those unrelated postings. So before spending a model call per job, rank
the pool by overlap between the candidate's skills and target role words and the
posting's title, tags and description. Pure code, explainable, unit tested.

Weights: words from the headline and direct queries say what the target role is
and count most in a title; words from lateral queries count less, because they
are deliberately adjacent; skills count in the title and (capped) in the body.
"""

from __future__ import annotations

import re

from ..schemas import CandidateProfile, Job, SearchQuery

_STOP = {"and", "or", "the", "a", "an", "of", "for", "with", "in", "to", "engineer", "developer", "senior", "junior", "lead", "working", "role", "seeking", "features", "owning"}
_ENGINEERING = {"engineer", "developer", "engineering", "software", "entwickler", "backend", "back-end"}
_WORD = re.compile(r"[a-z0-9+#.\-]+")


def _tokens(s: str) -> set[str]:
    return {t.strip(".-") for t in _WORD.findall(s.lower()) if len(t) > 1 and t not in _STOP}


def role_terms(profile: CandidateProfile, queries: list[SearchQuery]) -> tuple[set[str], set[str]]:
    core = _tokens(profile.headline)
    lateral: set[str] = set()
    for q in queries:
        (lateral if q.lateral else core).update(_tokens(q.query))
    return core, lateral - core


def skill_terms(profile: CandidateProfile) -> set[str]:
    terms: set[str] = set()
    for sk in profile.skills:
        terms |= _tokens(sk)
    return terms


def location_terms(profile: CandidateProfile) -> set[str]:
    terms = {"remote", "homeoffice", "home-office"} if profile.remote_ok else set()
    for loc in profile.locations_ok:
        terms |= _tokens(loc) - {"eu", "europe"}
    return terms


def lexical_prior(job: Job, skills: set[str], core: set[str], lateral: set[str], locs: set[str] = frozenset(), *, local_first: bool = False) -> float:
    title = _tokens(job.title)
    tags = _tokens(" ".join(job.tags))
    desc = _tokens(job.description[:12000])
    score = 0.0
    in_place = bool(_tokens(job.location) & locs)
    if in_place:
        score += 4.0 if local_first else 3.0  # physically where the candidate wants to be
    elif job.remote:
        score += 2.0 if local_first else 3.0  # reachable, but not the asked-for place
    score += 3.0 * len(title & core)
    score += 1.0 * len(title & lateral)
    score += 2.0 * len(title & skills)
    score += 1.0 * len(tags & (skills | core))
    score += 0.5 * min(len(desc & skills), 12)  # cap so long postings don't win by volume
    score += 0.5 * min(len(desc & core), 6)
    if not (title & _ENGINEERING):
        score *= 0.5  # not an engineering title: rarely a fit for an engineer
    return round(score, 2)


def rank_pool(jobs: list[Job], profile: CandidateProfile, queries: list[SearchQuery], location: str | None = None) -> list[tuple[Job, float]]:
    """With an explicit --location, that place drives the location terms and on-site beats remote."""
    skills = skill_terms(profile)
    core, lateral = role_terms(profile, queries)
    if location:
        from .locate import wanted_terms

        locs = wanted_terms(location) - {"eu", "europe"}
    else:
        locs = location_terms(profile)
    scored = [(j, lexical_prior(j, skills, core, lateral, locs, local_first=bool(location))) for j in jobs]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
