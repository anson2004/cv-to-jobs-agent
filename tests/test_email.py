"""The email template escapes text from job boards and the model."""

from jobad.deliver.email import render
from jobad.schemas import CandidateProfile, Job, JobScore, Recommendation, Seniority


def test_job_text_is_escaped():
    profile = CandidateProfile(name="Alex Chen", headline="h", years_experience=1, seniority=Seniority.mid, skills=[], domains=[], locations_ok=[], remote_ok=True, must_haves=[], dealbreakers=[], summary="s")
    job = Job(id="x:1", source="x", title="<script>alert(1)</script>Engineer", company="A&B", url="https://x/1", description="d")
    score = JobScore(job_id="x:1", skill_fit=4, seniority_fit=4, location_fit=4, growth=4, dealbreaker_hit=False, justification="j")
    rec = Recommendation(job_id="x:1", one_line_pitch="<b>pitch</b>", why_you=["a", "b"], what_to_address=["c"])
    html = render("r1", profile, [(job, score)], [rec])
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>pitch</b>" not in html and "A&amp;B" in html
