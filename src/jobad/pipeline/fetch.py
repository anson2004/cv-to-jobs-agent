"""Step 5: run queries against sources, normalise, dedup. No LLM.

Returns jobs ordered by how many queries hit them (a cheap relevance prior),
plus per-query counts for the adaptive planning branch.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..schemas import Job, SearchQuery
from ..sources import ALL_SOURCES, JobSource
from ..textutil import norm_key


@dataclass
class FetchResult:
    jobs: list[Job]
    fetched: int
    per_query: dict[str, int] = field(default_factory=dict)
    hits: Counter = field(default_factory=Counter)


def _dedup(jobs: list[Job]) -> list[Job]:
    seen_url: set[str] = set()
    seen_tc: set[tuple[str, str]] = set()
    out: list[Job] = []
    for j in jobs:
        u = j.url.split("?")[0].rstrip("/").lower()
        tc = (norm_key(j.title), norm_key(j.company))
        if u in seen_url or tc in seen_tc:
            continue
        seen_url.add(u)
        seen_tc.add(tc)
        out.append(j)
    return out


def fetch_jobs(queries: list[SearchQuery], cache_dir: Path, offline: bool, sources: list[type[JobSource]] | None = None) -> FetchResult:
    srcs = [S(cache_dir, offline=offline) for S in (sources or ALL_SOURCES)]
    raw: list[Job] = []
    per_query: dict[str, int] = {}
    hits: Counter = Counter()
    for q in queries:
        n = 0
        for s in srcs:
            try:
                found = s.search(q.query)
            except Exception as e:  # a dead source must not kill the run
                print(f"  ! {s.name} failed for '{q.query}': {e}")
                found = []
            for j in found:
                hits[j.id] += 1
            raw.extend(found)
            n += len(found)
        per_query[q.query] = n
    deduped = _dedup(raw)
    deduped.sort(key=lambda j: (-hits[j.id], j.posted_at or ""), reverse=False)
    return FetchResult(jobs=deduped, fetched=len(raw), per_query=per_query, hits=hits)
