"""Step 7c: a fact-checker agent reviews the writer's notes. Two agents, one bounded loop.

For each pick the checker sees the CV, the posting and the numbered claims (the
pitch and the "why you" bullets) and marks each supported or unsupported. If any
is unsupported, the writer rewrites that job's notes once and the checker looks
again. Claims still unsupported are dropped in code; if fewer than two bullets
are left, the job falls back to the scorer's own notes. One rewrite at most, so
a run costs between one and three extra calls per pick.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..llm import LLM
from ..prompts import load_prompt
from ..schemas import ClaimReport, Job, JobScore, Recommendation
from ..textutil import truncate
from .explain import job_block, notes_only

CV_CHARS = 8000
MIN_WHY_YOU = 2


@dataclass
class VerifyResult:
    recs: list[Recommendation]
    checked: int = 0  # claims checked in the first pass
    unsupported: int = 0  # unsupported in the first pass
    rewritten: int = 0  # picks whose notes were rewritten
    dropped: int = 0  # claims still unsupported after the rewrite, removed in code
    failed: int = 0  # picks left as drafted because a call failed

    def line(self) -> str:
        s = f"{self.checked} claims, {self.unsupported} unsupported; rewrote {self.rewritten}, dropped {self.dropped} claims"
        return s + (f", {self.failed} unchecked" if self.failed else "")


def claims(r: Recommendation) -> list[str]:
    """Index 0 is the pitch, then the "why you" bullets. Gaps are not claims of fit."""
    return [r.one_line_pitch, *r.why_you]


def check(llm: LLM, cv_text: str, j: Job, r: Recommendation, model: str) -> set[int]:
    """Indices of unsupported claims. A claim the checker skipped counts as supported."""
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(claims(r)))
    # No scorer notes here: they are model output, not a source of truth.
    user = f"CV:\n{truncate(cv_text, CV_CHARS)}\n\nJob posting:\n{job_block(j, None)}\n\nClaims:\n{numbered}"
    report = llm.complete_json(ClaimReport, step="verify", model=model, system=load_prompt("verify"), user=user, max_tokens=1500, meta={"job_id": j.id})
    n = len(claims(r))
    return {c.index for c in report.checks if c.verdict == "unsupported" and c.index < n}


def revise(llm: LLM, cv_text: str, j: Job, s: JobScore, r: Recommendation, bad: set[int], model: str) -> Recommendation:
    flagged = "\n".join(f"- {claims(r)[i]}" for i in sorted(bad))
    user = (
        f"CV:\n{truncate(cv_text, CV_CHARS)}\n\nJob:\n{job_block(j, s)}\n\n"
        f"Your draft:\n{json.dumps(r.model_dump(), indent=1)}\n\nUnsupported claims:\n{flagged}"
    )
    out = llm.complete_json(Recommendation, step="revise", model=model, system=load_prompt("revise"), user=user, max_tokens=1500, meta={"job_id": j.id})
    return out.model_copy(update={"job_id": j.id})


def drop_claims(j: Job, s: JobScore, r: Recommendation, bad: set[int]) -> Recommendation:
    why_you = [b for i, b in enumerate(r.why_you, start=1) if i not in bad]
    if len(why_you) < MIN_WHY_YOU:
        return notes_only(j, s)
    pitch = s.justification if 0 in bad else r.one_line_pitch
    return Recommendation(job_id=j.id, one_line_pitch=pitch, why_you=why_you, what_to_address=r.what_to_address)


def verify(llm: LLM, cv_text: str, picks: list[tuple[Job, JobScore]], recs: list[Recommendation], model: str) -> VerifyResult:
    res = VerifyResult(recs=[])
    for (j, s), draft in zip(picks, recs):
        try:
            bad = check(llm, cv_text, j, draft, model)
        except Exception:  # a failed check must not cost the email; keep the draft
            res.failed += 1
            res.recs.append(draft)
            continue
        res.checked += len(claims(draft))
        res.unsupported += len(bad)
        r = draft
        if bad:
            try:
                r = revise(llm, cv_text, j, s, draft, bad, model)
                res.rewritten += 1
                still = check(llm, cv_text, j, r, model)
            except Exception:  # no verified rewrite: drop the known-bad claims from the draft
                r, still = draft, bad
            if still:
                res.dropped += len(still)
                r = drop_claims(j, s, r, still)
        res.recs.append(r)
    return res
