from pathlib import Path

from .arbeitnow import ArbeitnowSource
from .base import JobSource, matches_query, query_terms
from .duunitori import DuunitoriSource
from .jobicy import JobicySource
from .remotive import RemotiveSource

# Default, always-on sources. Jobicy searches; the other two are feeds filtered locally.
ALL_SOURCES: list[type[JobSource]] = [JobicySource, RemotiveSource, ArbeitnowSource]


def build_sources(cache_dir: Path, offline: bool = False, *, duunitori: bool = False, area: str | None = None) -> list[JobSource]:
    """Instantiate the sources for a run. Duunitori only when explicitly enabled."""
    srcs: list[JobSource] = [S(cache_dir, offline=offline) for S in ALL_SOURCES]
    if duunitori:
        d = DuunitoriSource(cache_dir, offline=offline)
        d.area = area or None
        srcs.append(d)
    return srcs


__all__ = ["JobSource", "JobicySource", "RemotiveSource", "ArbeitnowSource", "DuunitoriSource", "ALL_SOURCES", "build_sources", "matches_query", "query_terms"]
