"""Jobicy public API: remote jobs, no key. https://jobicy.com/api/v2/remote-jobs

Unlike the feed sources, `tag=` really filters (single-word tags such as
python, backend, llm, java; verified 2026-10-12). One request per query using
the query's first keyword as the tag, then the full query is applied locally.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..schemas import Job
from ..textutil import strip_html
from .base import JobSource, matches_query, query_terms


class JobicySource(JobSource):
    name = "jobicy"
    kind = "search"
    URL = "https://jobicy.com/api/v2/remote-jobs"

    def _request(self, client: httpx.Client, query: str) -> Any:
        """Try each query term as the tag; Jobicy 400s on tags it does not know
        (e.g. 'ai'). Fall back to the untagged feed, which the local filter then narrows."""
        for tag in [*query_terms(query), None]:
            params: dict[str, Any] = {"count": 100}
            if tag:
                params["tag"] = tag
            r = client.get(self.URL, params=params)
            if r.status_code == 400 and tag:
                continue
            r.raise_for_status()
            return r.json()
        return {"jobs": []}

    def search(self, query: str) -> list[Job]:
        return [j for j in super().search(query) if matches_query(j, query)]

    def _parse(self, raw: Any) -> list[Job]:
        out: list[Job] = []
        for j in raw.get("jobs", []) or []:
            geo = j.get("jobGeo") or "Anywhere"
            out.append(
                Job(
                    id=f"jobicy:{j['id']}",
                    source=self.name,
                    title=(j.get("jobTitle") or "").strip(),
                    company=(j.get("companyName") or "").strip(),
                    location=f"Remote ({geo})",
                    remote=True,
                    url=j.get("url", ""),
                    description=strip_html(j.get("jobDescription") or j.get("jobExcerpt") or ""),
                    tags=list(j.get("jobIndustry") or []) + list(j.get("jobType") or []) + ([j["jobLevel"]] if j.get("jobLevel") else []),
                    posted_at=(j.get("pubDate") or "")[:10] or None,
                    salary=None,
                )
            )
        return out
