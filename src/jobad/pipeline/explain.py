"""Step 7b: one LLM call that writes the notes for the selected jobs."""

from __future__ import annotations

from ..llm import LLM
from ..prompts import load_prompt
from ..schemas import CandidateProfile, Job, JobScore, Recommendation, RecommendationSet
from ..textutil import truncate

DESCRIPTION_CHARS = 1500


def job_block(j: Job, s: JobScore | None, chars: int = DESCRIPTION_CHARS) -> str:
    notes = f"scorer notes: {s.justification} red flags: {', '.join(s.red_flags) or 'none'}\n" if s else ""
    return (
        f"job_id: {j.id}\ntitle: {j.title} at {j.company} ({j.location}{', remote' if j.remote else ''})\n"
        f"{notes}description:\n{truncate(j.description, chars)}"
    )


def notes_only(j: Job, s: JobScore) -> Recommendation:
    """Fallback built from the scorer's own notes, when no model-written notes can be used."""
    return Recommendation(job_id=j.id, one_line_pitch=s.justification, why_you=[f"Overall fit {s.overall:.1f}/5", f"Skill fit {s.skill_fit}/5, growth {s.growth}/5"], what_to_address=s.red_flags[:3] or ["Read the full posting."])


def explain(llm: LLM, profile: CandidateProfile, picks: list[tuple[Job, JobScore]], model: str, chars: int = DESCRIPTION_CHARS) -> list[Recommendation]:
    blocks = [job_block(j, s, chars) for j, s in picks]
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
