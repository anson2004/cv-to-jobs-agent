"""Arbeitnow job board API: Europe-heavy, no key. https://www.arbeitnow.com/api/job-board-api

The API ignores `search` and returns its latest postings, paged (verified 2026-10-12),
so it is treated as a feed source and a few pages are pulled once per run."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

import httpx
from pydantic import BaseModel

from ..schemas import Job
from ..textutil import strip_html
from .base import JobSource, JsonDict, NoneAsEmpty, Str, StrList


class ArbeitnowItem(BaseModel):
    slug: str
    title: Str = ""
    company_name: Str = ""
    location: Str = ""
    remote: bool | None = None
    url: Str = ""
    description: Str = ""
    tags: StrList = []
    job_types: StrList = []
    created_at: int | float | None = None  # unix seconds


class ArbeitnowFeed(BaseModel):
    data: Annotated[list[ArbeitnowItem], NoneAsEmpty] = []


class ArbeitnowSource(JobSource):
    name = "arbeitnow"
    kind = "feed"
    URL = "https://www.arbeitnow.com/api/job-board-api"
    PAGES = 4  # ~325 postings per page

    def _request(self, client: httpx.Client, query: str) -> JsonDict:
        data: list[Any] = []
        for page in range(1, self.PAGES + 1):
            r = client.get(self.URL, params={"page": page})
            r.raise_for_status()
            body: JsonDict = r.json()
            data.extend(body.get("data", []))
            if not body.get("links", {}).get("next"):
                break
        return {"data": data}

    def _parse(self, raw: JsonDict) -> list[Job]:
        out: list[Job] = []
        for j in ArbeitnowFeed.model_validate(raw).data:
            posted = datetime.fromtimestamp(j.created_at, tz=timezone.utc).date().isoformat() if j.created_at is not None else None
            out.append(
                Job(
                    id=f"arbeitnow:{j.slug}",
                    source=self.name,
                    title=j.title.strip(),
                    company=j.company_name.strip(),
                    location=j.location,
                    remote=bool(j.remote),
                    url=j.url,
                    description=strip_html(j.description),
                    tags=j.tags + j.job_types,
                    posted_at=posted,
                    salary=None,
                )
            )
        return out
