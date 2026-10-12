"""Job source protocol with a disk cache.

Two kinds of source:
- `search`: the API filters by query (Jobicy). The query is passed through.
- `feed`: the API ignores query parameters and returns its latest postings
  (Remotive and Arbeitnow do this, verified 2026-10-12). The feed is fetched
  once per run and the planned queries are applied locally as keyword filters,
  so the planner's queries still decide what enters the pool.

Every raw API response is cached under data/cache/<source>/<hash>.json so the
pipeline can run offline and a demo never depends on a third-party API being up.
`offline=True` reads cache only and returns [] on a miss.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

import httpx

from ..schemas import Job

_QUERY_STOP = {"engineer", "developer", "engineering", "senior", "junior", "remote", "jobs", "job", "role", "roles"}
_WORD = re.compile(r"[a-z0-9+#.\-]+")


def query_terms(query: str) -> list[str]:
    """'backend engineer python' -> ['backend', 'python']. Words that every posting has are dropped."""
    return [w for w in _WORD.findall(query.lower()) if w not in _QUERY_STOP and len(w) > 1]


def matches_query(job: Job, query: str) -> bool:
    """Local keyword filter for feed sources: every term must appear in title or description."""
    terms = query_terms(query)
    if not terms:
        return True
    hay = f"{job.title}\n{' '.join(job.tags)}\n{job.description}".lower()
    return all(t in hay for t in terms)


class JobSource(ABC):
    name: str = "base"
    kind: Literal["search", "feed"] = "search"

    def __init__(self, cache_dir: Path, offline: bool = False):
        self.cache_dir = cache_dir / self.name
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self._feed: list[Job] | None = None

    # -- subclass contract ---------------------------------------------
    @abstractmethod
    def _request(self, client: httpx.Client, query: str) -> Any:
        """Hit the API and return the parsed JSON body. For feed sources `query` is ignored."""

    @abstractmethod
    def _parse(self, raw: Any) -> list[Job]:
        """Map the raw body to Job objects."""

    # -- public --------------------------------------------------------
    def search(self, query: str) -> list[Job]:
        if self.kind == "feed":
            if self._feed is None:
                self._feed = self._parse(self._fetch("__feed__"))
            return [j for j in self._feed if matches_query(j, query)]
        return self._parse(self._fetch(query))

    # -- fetch + cache -------------------------------------------------
    def _fetch(self, query: str) -> Any:
        raw = self._cached(query)
        if raw is None:
            if self.offline:
                return self._empty()
            with httpx.Client(timeout=25, headers={"User-Agent": "job-ad-orchestrator/0.1 (demo)"}) as client:
                raw = self._request(client, query)
            self._write_cache(query, raw)
        return raw

    def _empty(self) -> Any:
        return {}

    def _key(self, query: str) -> Path:
        h = hashlib.sha1(query.strip().lower().encode()).hexdigest()[:16]
        return self.cache_dir / f"{h}.json"

    def _cached(self, query: str) -> Any | None:
        p = self._key(query)
        if not p.exists():
            return None
        return json.loads(p.read_text())["body"]

    def _write_cache(self, query: str, body: Any) -> None:
        self._key(query).write_text(json.dumps({"query": query, "fetched_at": time.time(), "body": body}))
