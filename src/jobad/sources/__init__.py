from .arbeitnow import ArbeitnowSource
from .base import JobSource, matches_query, query_terms
from .jobicy import JobicySource
from .remotive import RemotiveSource

# Order matters only for logging. Jobicy searches; the other two are feeds filtered locally.
ALL_SOURCES: list[type[JobSource]] = [JobicySource, RemotiveSource, ArbeitnowSource]

__all__ = ["JobSource", "JobicySource", "RemotiveSource", "ArbeitnowSource", "ALL_SOURCES", "matches_query", "query_terms"]
