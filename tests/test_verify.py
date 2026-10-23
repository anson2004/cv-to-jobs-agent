"""The fact-check loop with a fake model: check, rewrite once, drop what is still unsupported. No network, no LLM."""

from jobad.pipeline import verify as v
from jobad.schemas import ClaimCheck, ClaimReport, Job, JobScore, Recommendation

JOB = Job(id="x:1", source="x", title="Backend Engineer", company="Co", url="u", description="Python, Postgres.")
SCORE = JobScore(job_id="x:1", skill_fit=4, seniority_fit=4, location_fit=5, growth=3, dealbreaker_hit=False, justification="Strong Python match.")
DRAFT = Recommendation(job_id="x:1", one_line_pitch="Your Python fits.", why_you=["Python for 6 years", "Led a Kafka migration", "Postgres tuning"], what_to_address=["No Go"])
FIXED = Recommendation(job_id="wrong-id", one_line_pitch="Your Python fits.", why_you=["Python for 6 years", "Postgres tuning"], what_to_address=["No Go"])


def _report(bad: set[int], n: int) -> ClaimReport:
    return ClaimReport(checks=[ClaimCheck(index=i, verdict="unsupported" if i in bad else "supported", evidence="e") for i in range(n)])


class FakeLLM:
    """Answers each `verify` call with the next set of unsupported indices; `revise` returns FIXED."""

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.steps = []

    def complete_json(self, schema, *, step, user, **kw):
        self.steps.append(step)
        if step == "revise":
            assert "Led a Kafka migration" in user.split("Unsupported claims:")[1]
            return FIXED
        n = user.split("Claims:\n")[1].count("\n") + 1
        return _report(self.verdicts.pop(0), n)


def test_all_supported_is_one_call_and_unchanged():
    llm = FakeLLM([set()])
    res = v.verify(llm, "cv", [(JOB, SCORE)], [DRAFT], "m")
    assert llm.steps == ["verify"] and res.recs == [DRAFT]
    assert (res.checked, res.unsupported, res.rewritten, res.dropped) == (4, 0, 0, 0)


def test_unsupported_claim_is_rewritten_and_rechecked():
    llm = FakeLLM([{2}, set()])  # index 2 = second "why you" bullet
    res = v.verify(llm, "cv", [(JOB, SCORE)], [DRAFT], "m")
    assert llm.steps == ["verify", "revise", "verify"]
    assert res.recs[0].why_you == ["Python for 6 years", "Postgres tuning"]
    assert res.recs[0].job_id == "x:1"  # the model's id is never trusted
    assert (res.unsupported, res.rewritten, res.dropped) == (1, 1, 0)


def test_still_unsupported_after_rewrite_is_dropped():
    llm = FakeLLM([{2}, {0, 2}])  # the rewrite's pitch and its second bullet still fail
    res = v.verify(llm, "cv", [(JOB, SCORE)], [DRAFT], "m")
    # one bullet left is below the minimum, so the scorer's own notes are used
    assert res.recs[0] == v.notes_only(JOB, SCORE)
    assert res.dropped == 2


def test_drop_keeps_supported_bullets_and_swaps_a_bad_pitch():
    r = v.drop_claims(JOB, SCORE, DRAFT, {0, 2})
    assert r.one_line_pitch == SCORE.justification
    assert r.why_you == ["Python for 6 years", "Postgres tuning"]


def test_failed_check_keeps_the_draft():
    class Broken(FakeLLM):
        def complete_json(self, schema, **kw):
            raise RuntimeError("model down")

    res = v.verify(Broken([]), "cv", [(JOB, SCORE)], [DRAFT], "m")
    assert res.recs == [DRAFT] and res.failed == 1
