"""Step 7b: one LLM call that writes the notes for the selected jobs."""

from __future__ import annotations

from ..llm import LLM
from ..prompts import load_prompt
from ..schemas import CandidateProfile, Job, JobScore, Recommendation, RecommendationSet
from ..textutil import truncate


def explain(llm: LLM, profile: CandidateProfile, picks: list[tuple[Job, JobScore]], model: str, chars: int = 1500) -> list[Recommendation]:
    blocks = []
    for j, s in picks:
        blocks.append(
            f"job_id: {j.id}\ntitle: {j.title} at {j.company} ({j.location}{', remote' if j.remote else ''})\n"
            f"scorer notes: {s.justification} red flags: {', '.join(s.red_flags) or 'none'}\n"
            f"description:\n{truncate(j.description, chars)}"
        )
    user = f"Candidate profile:\n{profile.model_dump_json(indent=1)}\n\nJobs:\n\n" + "\n\n---\n\n".join(blocks)
    out = llm.complete_json(
        RecommendationSet,
        step="explain",
        model=model,
        system=load_prompt("explain"),
        user=user,
        reasoning_effort="low",
        max_tokens=4000,
    )
    # Re-align by job_id in case the model reordered or dropped one.
    by_id = {r.job_id: r for r in out.recommendations}
    result: list[Recommendation] = []
    for j, _ in picks:
        r = by_id.get(j.id)
        if r is None:
            r = Recommendation(job_id=j.id, one_line_pitch=f"{j.title} at {j.company} scored well on fit.", why_you=["See scorer notes.", "Strong overall score."], what_to_address=["Read the full posting."])
        result.append(r)
    return result
