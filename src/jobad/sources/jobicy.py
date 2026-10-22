"""Jobicy public API: remote jobs, no key. https://jobicy.com/api/v2/remote-jobs

Unlike the feed sources, `tag=` really filters (single-word tags such as
python, backend, llm, java; verified 2026-10-12). One request per query using
the query's first keyword as the tag, then the full query is applied locally.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from pydantic import BaseModel

from ..schemas import Job
from ..textutil import strip_html
from .base import JobSource, JsonDict, NoneAsEmpty, Str, StrList, matches_query, query_terms


class JobicyItem(BaseModel):
    """Field names follow the API's camelCase."""

    id: int | str
    jobTitle: Str = ""
    companyName: Str = ""
    jobGeo: Str = ""
    url: Str = ""
    jobDescription: Str = ""
    jobExcerpt: Str = ""
    jobIndustry: StrList = []
    jobType: StrList = []
    jobLevel: Str = ""
    pubDate: Str = ""


class JobicyResponse(BaseModel):
    jobs: Annotated[list[JobicyItem], NoneAsEmpty] = []


class JobicySource(JobSource):
    name = "jobicy"
    kind = "search"
    URL = "https://jobicy.com/api/v2/remote-jobs"

    def _request(self, client: httpx.Client, query: str) -> JsonDict:
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
            body: JsonDict = r.json()
            return body
        return {"jobs": []}

    def search(self, query: str) -> list[Job]:
        return [j for j in super().search(query) if matches_query(j, query)]

    def _parse(self, raw: JsonDict) -> list[Job]:
        out: list[Job] = []
        for j in JobicyResponse.model_validate(raw).jobs:
            out.append(
                Job(
                    id=f"jobicy:{j.id}",
                    source=self.name,
                    title=j.jobTitle.strip(),
                    company=j.companyName.strip(),
                    location=f"Remote ({j.jobGeo or 'Anywhere'})",
                    remote=True,
                    url=j.url,
                    description=strip_html(j.jobDescription or j.jobExcerpt),
                    tags=j.jobIndustry + j.jobType + ([j.jobLevel] if j.jobLevel else []),
                    posted_at=j.pubDate[:10] or None,
                    salary=None,
                )
            )
        return out
