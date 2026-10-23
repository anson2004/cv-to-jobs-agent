"""Step 5b: cheap lexical prior to decide which jobs get the expensive model call.

The job APIs are keyword-matched loosely (Arbeitnow in particular returns many
unrelated postings for any query). Counting how many queries hit a job rewards
exactly those unrelated postings. So before spending a model call per job, rank
the pool by overlap between the candidate's skills and target role words and the
posting's title, tags and description. Pure code, explainable, unit tested.

Weights: words from the headline and direct queries say what the target role is
and count most in a title; words from lateral queries count less, because they
are deliberately adjacent; skills count in the title and (capped) in the body.
A title that shares no word with the candidate's target roles or skills is
halved: an office-assistant posting rarely fits a treasury analyst, and an
accountant posting rarely fits an engineer. Nothing here assumes a field.
"""

from __future__ import annotations

import re
from collections.abc import Set as AbstractSet

from ..schemas import CandidateProfile, Job, SearchQuery

_STOP = {"and", "or", "the", "a", "an", "of", "for", "with", "in", "to", "engineer", "developer", "senior", "junior", "lead", "working", "role", "seeking", "features", "owning"}
# Words that say nothing about the field, so they never count as a role match.
_NOT_ROLE = {"with", "from", "into", "junior", "senior", "lead", "principal", "staff", "head", "aspiring", "experienced", "seeking", "specializing", "focusing", "moving", "working", "owning", "features", "role", "roles", "position"}
_WORD = re.compile(r"[a-z0-9+#.\-äöå]+")


def _tokens(s: str) -> set[str]:
    return {t.strip(".-") for t in _WORD.findall(s.lower()) if len(t) > 1 and t not in _STOP}


def role_terms(profile: CandidateProfile, queries: list[SearchQuery]) -> tuple[set[str], set[str]]:
    core = _tokens(profile.headline)
    lateral: set[str] = set()
    for q in queries:
        (lateral if q.lateral else core).update(_tokens(q.query))
    return core, lateral - core


def role_words(profile: CandidateProfile, queries: list[SearchQuery]) -> set[str]:
    """Words naming the roles the candidate wants, kept whole ("engineer", "analyst", "treasury")."""
    words = set(_WORD.findall(profile.headline.lower()))
    for q in queries:
        words |= set(_WORD.findall(q.query.lower()))
    return {w.strip(".-") for w in words if len(w.strip(".-")) >= 4 and w not in _NOT_ROLE}


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


def lexical_prior(job: Job, skills: set[str], core: set[str], lateral: set[str], locs: AbstractSet[str] = frozenset(), *, local_first: bool = False, roles: AbstractSet[str] = frozenset()) -> float:
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
    # Substring match, because Finnish titles are compounds ("kirjanpitäjä" in "pääkirjanpitäjä").
    title_l = job.title.lower()
    if roles and not (any(w in title_l for w in roles) or title & skills):
        score *= 0.5  # nothing in the title points at the candidate's field
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
    roles = role_words(profile, queries)
    scored = [(j, lexical_prior(j, skills, core, lateral, locs, local_first=bool(location), roles=roles)) for j in jobs]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
