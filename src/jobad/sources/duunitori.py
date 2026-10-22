"""Duunitori (duunitori.fi), Finland's largest job board. OPT-IN ONLY.

Endpoint: https://duunitori.fi/api/v1/jobentries?search=<term>&area=<city>
It is undocumented, and duunitori.fi/robots.txt disallows automated access.
This source is therefore off by default (DUUNITORI_ENABLED=true turns it on),
makes a small number of requests per run with an identifying User-Agent and a
pause between calls, and caches everything. Enable it for personal use only.

The search ANDs its terms and matches titles, so multi-word planner queries
return nothing for a mid-sized city. The source is modelled as a feed: a few
broad tech terms are swept for the area once per run, and the planner's
queries are applied locally with any-term matching (Finnish postings still
carry English tech words like Python, AWS, Go).
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
from pydantic import BaseModel

from ..schemas import Job
from ..textutil import strip_html
from .base import JobSource, JsonDict, NoneAsEmpty, Str, query_terms

SWEEP_TERMS = ["software", "developer", "engineer", "ohjelmisto", "data", "cloud", "devops", "python", "java", "backend", "tekoäly", "ai"]
MAX_PAGES = 3
PAUSE_S = 1.0
_REMOTE = re.compile(r"\b(etätyö|etänä|remote|hybridi|hybrid)\b", re.I)


class DuunitoriItem(BaseModel):
    slug: str
    heading: Str = ""
    company_name: Str = ""
    municipality_name: Str = ""
    date_posted: Str = ""
    descr: Str = ""


class DuunitoriFeed(BaseModel):
    results: Annotated[list[DuunitoriItem], NoneAsEmpty] = []


class DuunitoriSource(JobSource):
    name = "duunitori"
    kind = "feed"
    URL = "https://duunitori.fi/api/v1/jobentries"
    area: str | None = None  # set by the pipeline from the location filter, e.g. "Tampere"

    def _request(self, client: httpx.Client, query: str) -> JsonDict:
        results: dict[str, JsonDict] = {}
        for term in SWEEP_TERMS:
            for page in range(1, MAX_PAGES + 1):
                params: dict[str, Any] = {"search": term, "page": page}
                if self.area:
                    params["area"] = self.area
                r = client.get(self.URL, params=params)
                if r.status_code != 200:
                    break
                body: JsonDict = r.json()
                for it in body.get("results", []):
                    results.setdefault(it["slug"], it)
                time.sleep(PAUSE_S)
                if not body.get("next"):
                    break
        return {"results": list(results.values()), "area": self.area}

    def _key(self, query: str) -> Path:
        return super()._key(f"{query}|{self.area or 'all'}")

    def search(self, query: str) -> list[Job]:
        if self._feed is None:
            self._feed = self._parse(self._fetch("__feed__"))
        terms = query_terms(query)
        if not terms:
            return list(self._feed)
        out: list[Job] = []
        for j in self._feed:
            hay = f"{j.title}\n{j.description}".lower()
            if any(t in hay for t in terms):
                out.append(j)
        return out

    def _parse(self, raw: JsonDict) -> list[Job]:
        out: list[Job] = []
        for j in DuunitoriFeed.model_validate(raw).results:
            heading = j.heading.strip()
            descr = strip_html(j.descr)
            posted = j.date_posted[:10] or None
            try:
                datetime.fromisoformat(posted) if posted else None
            except ValueError:
                posted = None
            out.append(
                Job(
                    id=f"duunitori:{j.slug}",
                    source=self.name,
                    title=heading,
                    company=j.company_name.strip(),
                    location=f"{j.municipality_name or 'Finland'}, Finland",
                    remote=bool(_REMOTE.search(heading) or _REMOTE.search(descr[:600])),
                    url=f"https://duunitori.fi/tyopaikat/tyo/{j.slug}",
                    description=descr,
                    tags=[],
                    posted_at=posted,
                    salary=None,
                )
            )
        return out
