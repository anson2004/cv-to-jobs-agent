"""Step 4: profile -> search queries. One LLM call, strong model.

`plan_more` is the adaptive branch: if the first round returned too few jobs,
the model sees what it tried and the counts, and proposes different queries.
"""

from __future__ import annotations

from ..llm import LLM
from ..prompts import load_prompt
from ..schemas import CandidateProfile, QueryPlan


def plan_queries(llm: LLM, profile: CandidateProfile, model: str) -> QueryPlan:
    return llm.complete_json(
        QueryPlan,
        step="plan_queries",
        model=model,
        system=load_prompt("plan_queries"),
        user=f"Candidate profile:\n{profile.model_dump_json(indent=1)}",
        reasoning_effort="medium",
        max_tokens=1200,
    )


def plan_more(llm: LLM, profile: CandidateProfile, tried: dict[str, int], model: str, want: int = 3) -> QueryPlan:
    tried_txt = "\n".join(f"- '{q}': {n} jobs" for q, n in tried.items())
    return llm.complete_json(
        QueryPlan,
        step="plan_queries_more",
        model=model,
        system=load_prompt("plan_queries") + f"\n\nThis is a second round. Produce exactly {want} new queries that are clearly different from the ones already tried. Prefer broader or differently-worded queries where the tried ones returned few jobs.",
        user=f"Candidate profile:\n{profile.model_dump_json(indent=1)}\n\nAlready tried (query: jobs found):\n{tried_txt}",
        reasoning_effort="medium",
        max_tokens=800,
    )
