"""Duunitori (duunitori.fi), Finland's largest job board. OPT-IN ONLY.

Endpoint: https://duunitori.fi/api/v1/jobentries?search=<term>&area=<city>
It is undocumented, and duunitori.fi/robots.txt disallows automated access.
This source is therefore off by default (DUUNITORI_ENABLED=true turns it on),
makes a small number of requests per run with an identifying User-Agent and a
pause between calls, and caches everything. Enable it for personal use only.

The search ANDs its terms and matches titles, so a multi-word planner query
returns only exact title matches. So each query is searched whole, and each of
its distinctive words on its own, and the results are merged: "cash manager"
searches "cash manager" and "cash". Generic words like "manager" or
"specialist" are never searched alone, because they match every field. The
words come from the planner, so from the CV; the source has no built-in field. Each word is cached
per area, and at most MAX_TERMS new words are fetched per run.

`area` may list several cities ("Tampere, Helsinki"); each is searched
separately and the results merged.
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
from .base import JobSource, JsonDict, NoneAsEmpty, Str, query_terms, split_places

MAX_TERMS = 24  # new searches per run; cached ones cost nothing
# Role words shared by every field: searched alone they return sales, HR and IT jobs alike.
GENERIC = {"manager", "specialist", "analyst", "administrator", "assistant", "coordinator", "expert", "consultant", "officer", "associate", "lead", "head", "team", "asiantuntija", "päällikkö", "koordinaattori", "assistentti", "analyytikko", "konsultti"}


def search_terms(query: str) -> list[str]:
    """The whole query, then each word that is specific enough to search alone."""
    words = query_terms(query)
    out = [" ".join(words)] if len(words) > 1 else []
    return out + [w for w in words if w not in GENERIC]
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
    kind = "search"
    URL = "https://duunitori.fi/api/v1/jobentries"
    area: str | None = None  # set by the pipeline from the location filter, e.g. "Tampere" or "Tampere, Helsinki"

    def __init__(self, cache_dir: Path, offline: bool = False):
        super().__init__(cache_dir, offline)
        self._new_terms = 0

    def _request(self, client: httpx.Client, query: str) -> JsonDict:
        """`query` is one search term, searched in every area."""
        results: dict[str, JsonDict] = {}
        areas: list[str | None] = [a for a in split_places(self.area or "")] or [None]
        for area in areas:
            for page in range(1, MAX_PAGES + 1):
                params: dict[str, Any] = {"search": query, "page": page}
                if area:
                    params["area"] = area
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
        out: dict[str, Job] = {}
        for term in search_terms(query):
            if self._cached(term) is None and not self.offline:
                if self._new_terms >= MAX_TERMS:
                    continue  # politeness cap: no more new requests this run
                self._new_terms += 1
            for j in self._parse(self._fetch(term)):
                out.setdefault(j.id, j)
        return list(out.values())

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
