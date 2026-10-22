"""Remotive public API: remote jobs, no key. https://remotive.com/api/remote-jobs

The public endpoint ignores `search`/`category` and returns a short feed of recent
postings (verified 2026-10-12), so it is treated as a feed source."""

from __future__ import annotations

from typing import Annotated

import httpx
from pydantic import BaseModel

from ..schemas import Job
from ..textutil import strip_html
from .base import JobSource, JsonDict, NoneAsEmpty, Str, StrList


class RemotiveItem(BaseModel):
    id: int | str
    title: Str = ""
    company_name: Str = ""
    candidate_required_location: Str = ""
    url: Str = ""
    description: Str = ""
    tags: StrList = []
    category: Str = ""
    publication_date: str | None = None
    salary: Str = ""


class RemotiveFeed(BaseModel):
    jobs: Annotated[list[RemotiveItem], NoneAsEmpty] = []


class RemotiveSource(JobSource):
    name = "remotive"
    kind = "feed"
    URL = "https://remotive.com/api/remote-jobs"

    def _request(self, client: httpx.Client, query: str) -> JsonDict:
        r = client.get(self.URL)
        r.raise_for_status()
        body: JsonDict = r.json()
        return body

    def _parse(self, raw: JsonDict) -> list[Job]:
        out: list[Job] = []
        for j in RemotiveFeed.model_validate(raw).jobs:
            out.append(
                Job(
                    id=f"remotive:{j.id}",
                    source=self.name,
                    title=j.title.strip(),
                    company=j.company_name.strip(),
                    location=j.candidate_required_location or "Remote",
                    remote=True,
                    url=j.url,
                    description=strip_html(j.description),
                    tags=j.tags + ([j.category] if j.category else []),
                    posted_at=j.publication_date,
                    salary=j.salary or None,
                )
            )
        return out
