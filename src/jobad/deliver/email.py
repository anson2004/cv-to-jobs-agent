"""Step 8: render an HTML email and send it, or write it to disk.

Sends through Resend when RESEND_API_KEY and TO_EMAIL are set. Otherwise (or
with dry_run) writes data/out/<run_id>.html so the demo still has an artifact.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import Settings
from ..schemas import CandidateProfile, Job, JobScore, Recommendation

_env = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=select_autoescape(["html"]))


def render(run_id: str, profile: CandidateProfile, picks: list[tuple[Job, JobScore]], recs: list[Recommendation]) -> str:
    tpl = _env.get_template("email.html.j2")
    items = [{"job": j, "score": s, "rec": r} for (j, s), r in zip(picks, recs)]
    return tpl.render(run_id=run_id, profile=profile, items=items)


def deliver(settings: Settings, run_id: str, profile: CandidateProfile, picks: list[tuple[Job, JobScore]], recs: list[Recommendation], *, dry_run: bool = False) -> str:
    html = render(run_id, profile, picks, recs)
    settings.out_dir.mkdir(parents=True, exist_ok=True)
    out = settings.out_dir / f"{run_id}.html"
    out.write_text(html)

    if dry_run or not (settings.resend_api_key and settings.to_email):
        reason = "dry run" if dry_run else "no RESEND_API_KEY/TO_EMAIL"
        return f"written to {out} ({reason})"

    import resend

    resend.api_key = settings.resend_api_key
    subject = f"{len(picks)} jobs for {profile.name.split()[0]}: " + ", ".join(j.title for j, _ in picks[:2]) + ("…" if len(picks) > 2 else "")
    r = resend.Emails.send({"from": settings.from_email, "to": [settings.to_email], "subject": subject, "html": html})
    return f"emailed {settings.to_email} (resend id {r.get('id', '?')}); copy at {out}"
