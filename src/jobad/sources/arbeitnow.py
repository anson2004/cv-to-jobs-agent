"""Arbeitnow job board API: Europe-heavy, no key. https://www.arbeitnow.com/api/job-board-api

The API ignores `search` and returns its latest postings, paged (verified 2026-10-12),
so it is treated as a feed source and a few pages are pulled once per run."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from ..schemas import Job
from ..textutil import strip_html
from .base import JobSource


class ArbeitnowSource(JobSource):
    name = "arbeitnow"
    kind = "feed"
    URL = "https://www.arbeitnow.com/api/job-board-api"
    PAGES = 4  # ~325 postings per page

    def _request(self, client: httpx.Client, query: str) -> Any:
        data: list[dict] = []
        for page in range(1, self.PAGES + 1):
            r = client.get(self.URL, params={"page": page})
            r.raise_for_status()
            body = r.json()
            data.extend(body.get("data", []))
            if not body.get("links", {}).get("next"):
                break
        return {"data": data}

    def _parse(self, raw: Any) -> list[Job]:
        out: list[Job] = []
        for j in raw.get("data", []):
            ts = j.get("created_at")
            posted = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if isinstance(ts, (int, float)) else None
            out.append(
                Job(
                    id=f"arbeitnow:{j['slug']}",
                    source=self.name,
                    title=j.get("title", "").strip(),
                    company=j.get("company_name", "").strip(),
                    location=j.get("location", "") or "",
                    remote=bool(j.get("remote")),
                    url=j.get("url", ""),
                    description=strip_html(j.get("description", "")),
                    tags=list(j.get("tags") or []) + list(j.get("job_types") or []),
                    posted_at=posted,
                    salary=None,
                )
            )
        return out
