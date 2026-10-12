"""Remotive public API: remote jobs, no key. https://remotive.com/api/remote-jobs

The public endpoint ignores `search`/`category` and returns a short feed of recent
postings (verified 2026-10-12), so it is treated as a feed source."""

from __future__ import annotations

from typing import Any

import httpx

from ..schemas import Job
from ..textutil import strip_html
from .base import JobSource


class RemotiveSource(JobSource):
    name = "remotive"
    kind = "feed"
    URL = "https://remotive.com/api/remote-jobs"

    def _request(self, client: httpx.Client, query: str) -> Any:
        r = client.get(self.URL)
        r.raise_for_status()
        return r.json()

    def _parse(self, raw: Any) -> list[Job]:
        out: list[Job] = []
        for j in raw.get("jobs", []):
            out.append(
                Job(
                    id=f"remotive:{j['id']}",
                    source=self.name,
                    title=j.get("title", "").strip(),
                    company=j.get("company_name", "").strip(),
                    location=j.get("candidate_required_location", "") or "Remote",
                    remote=True,
                    url=j.get("url", ""),
                    description=strip_html(j.get("description", "")),
                    tags=list(j.get("tags") or []) + ([j["category"]] if j.get("category") else []),
                    posted_at=j.get("publication_date"),
                    salary=j.get("salary") or None,
                )
            )
        return out
