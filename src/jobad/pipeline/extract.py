"""Step 3: CV text -> CandidateProfile. One LLM call, strong model."""

from __future__ import annotations

from ..llm import LLM
from ..prompts import load_prompt
from ..schemas import CandidateProfile


def extract_profile(llm: LLM, cv_text: str, model: str) -> CandidateProfile:
    return llm.complete_json(
        CandidateProfile,
        step="extract_profile",
        model=model,
        system=load_prompt("extract_profile"),
        user=f"CV:\n\n{cv_text}",
        reasoning_effort="medium",
        max_tokens=1500,
    )
