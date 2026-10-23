"""Step 4, team variant: a coordinator and one search agent per group of job boards.

The coordinator (one call) writes a brief: target roles, roles to avoid, what a
fit looks like. Each worker gets the brief, its own boards and its own prompt,
and runs the bounded search loop from agentic_plan on those boards only:
  remote boards  Jobicy, Remotive, Arbeitnow, searched in English
  finland        Duunitori, searched in Finnish and English
Workers run in parallel. Code, not the model, tags every query with its
worker's sources, so fetch runs it only there. A worker that fails, or ends
without searching, falls back to a single planning call with its own prompt.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ..llm import LLM
from ..prompts import load_prompt
from ..schemas import CandidateProfile, QueryPlan, SearchBrief, SearchQuery
from ..sources import JobSource
from .agentic_plan import agentic_plan

WORKER_SEARCHES = 4
WORKER_TURNS = 6


@dataclass
class Team:
    name: str
    prompt: str
    sources: list[JobSource]


@dataclass
class WorkerResult:
    team: str
    queries: list[SearchQuery]
    searches: list[tuple[str, int]] = field(default_factory=list)  # (query, matches)
    fallback: bool = False


@dataclass
class TeamResult:
    brief: SearchBrief
    workers: list[WorkerResult]

    @property
    def plan(self) -> QueryPlan:
        return QueryPlan.model_construct(queries=[q for w in self.workers for q in w.queries])


def build_teams(sources: list[JobSource]) -> list[Team]:
    local = [s for s in sources if s.name == "duunitori"]
    remote = [s for s in sources if s.name != "duunitori"]
    teams = [Team("remote boards", "plan_queries", remote)] if remote else []
    if local:
        teams.append(Team("finland", "search_finland", local))
    return teams


def write_brief(llm: LLM, profile: CandidateProfile, model: str) -> SearchBrief:
    return llm.complete_json(
        SearchBrief,
        step="plan_brief",
        model=model,
        system=load_prompt("search_brief"),
        user=f"Candidate profile:\n{profile.model_dump_json(indent=1)}",
        max_tokens=800,
    )


def _context(brief: SearchBrief, team: Team) -> str:
    return (
        f"Brief from the coordinator:\n{brief.model_dump_json(indent=1)}\n\n"
        f"You search only these boards: {', '.join(s.name for s in team.sources)}.\n\n"
    )


def run_worker(llm: LLM, profile: CandidateProfile, brief: SearchBrief, team: Team, model: str, cache_dir: Path) -> WorkerResult:
    step = f"plan_team:{team.name}"
    ctx = _context(brief, team)
    try:
        ar = agentic_plan(llm, profile, model, cache_dir, sources=team.sources, prompt=team.prompt, context=ctx, max_searches=WORKER_SEARCHES, max_turns=WORKER_TURNS, step=step)
        if ar.searches or not ar.forced_submit:  # searched, or submitted on its own
            return WorkerResult(team.name, _route(ar.plan.queries, team), ar.searches)
    except Exception:  # small local models sometimes cannot drive tools; one plain call instead
        pass
    plan = llm.complete_json(QueryPlan, step=f"{step}:fallback", model=model, system=load_prompt(team.prompt), user=f"Candidate profile:\n{profile.model_dump_json(indent=1)}\n\n{ctx}", max_tokens=1200)
    return WorkerResult(team.name, _route(plan.queries, team), fallback=True)


def _route(queries: list[SearchQuery], team: Team) -> list[SearchQuery]:
    names = [s.name for s in team.sources]
    return [q.model_copy(update={"sources": names}) for q in queries]


def team_plan(llm: LLM, profile: CandidateProfile, model: str, cache_dir: Path, sources: list[JobSource]) -> TeamResult:
    brief = write_brief(llm, profile, model)
    teams = build_teams(sources)
    with ThreadPoolExecutor(max_workers=len(teams) or 1) as pool:
        workers = list(pool.map(lambda t: run_worker(llm, profile, brief, t, model, cache_dir), teams))
    return TeamResult(brief, workers)
