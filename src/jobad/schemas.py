"""Data contracts for the pipeline.

Every LLM output is validated against one of these models. Everything that can
be computed in code (overall score, ids, timestamps) is computed in code, not
asked of the model.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, computed_field


class Seniority(str, Enum):
    junior = "junior"
    mid = "mid"
    senior = "senior"
    lead = "lead"


class CandidateProfile(BaseModel):
    name: str
    headline: str = Field(description="One line, e.g. 'Senior backend engineer moving into AI products'")
    years_experience: int = Field(ge=0, le=60)
    seniority: Seniority
    skills: list[str] = Field(description="Concrete, searchable skills: languages, frameworks, platforms")
    domains: list[str] = Field(description="Industries or problem areas worked in")
    locations_ok: list[str] = Field(description="Cities or countries the candidate will work in")
    remote_ok: bool
    must_haves: list[str] = Field(description="Things a job must have for the candidate to apply")
    dealbreakers: list[str] = Field(description="Things that rule a job out")
    summary: str = Field(description="Three sentences a recruiter would read first")


class SearchQuery(BaseModel):
    query: str = Field(description="Short keyword query, 2-5 words, as typed into a job board")
    reason: str = Field(description="Why this query for this candidate")
    lateral: bool = Field(default=False, description="True if this is an adjacent role the candidate may not have considered")


class QueryPlan(BaseModel):
    queries: list[SearchQuery] = Field(min_length=3, max_length=10)


class Job(BaseModel):
    id: str = Field(description="'<source>:<external id>'")
    source: str
    title: str
    company: str
    location: str = ""
    remote: bool = False
    url: str
    description: str = Field(description="Plain text, html stripped")
    tags: list[str] = []
    posted_at: str | None = None
    salary: str | None = None


class JobScore(BaseModel):
    job_id: str
    skill_fit: int = Field(ge=0, le=5, description="Overlap between required skills and candidate skills")
    seniority_fit: int = Field(ge=0, le=5, description="Level of the role vs candidate level; too junior or too senior both score low")
    location_fit: int = Field(ge=0, le=5, description="Remote/location compatibility")
    growth: int = Field(ge=0, le=5, description="Does this role move the candidate toward their headline?")
    dealbreaker_hit: bool = Field(description="True if the job matches any dealbreaker")
    justification: str = Field(description="One or two sentences")
    red_flags: list[str] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall(self) -> float:
        """Weighted 0-5. Weights are a product decision, documented in README."""
        base = (
            0.40 * self.skill_fit
            + 0.25 * self.seniority_fit
            + 0.15 * self.location_fit
            + 0.20 * self.growth
        )
        if self.dealbreaker_hit:
            base -= 2.0
        return round(max(base, 0.0), 2)


class Recommendation(BaseModel):
    job_id: str
    one_line_pitch: str = Field(description="Why this job, in one sentence addressed to the candidate")
    why_you: list[str] = Field(min_length=2, max_length=4, description="Concrete matches between CV and job")
    what_to_address: list[str] = Field(min_length=1, max_length=3, description="Gaps to cover in a cover letter")


class RecommendationSet(BaseModel):
    recommendations: list[Recommendation]


class RunSummary(BaseModel):
    run_id: str
    profile: CandidateProfile
    plan: QueryPlan
    fetched: int
    deduped: int
    scored: int
    top: list[tuple[Job, JobScore, Recommendation]]
    delivered_to: str
