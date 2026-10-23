"""Tests for the parts that must never need a model: scoring arithmetic, dedup, diversity."""

from jobad.pipeline.fetch import _dedup
from jobad.pipeline.select import select_top
from jobad.schemas import Job, JobScore


def job(i: str, title: str, company: str, url: str | None = None) -> Job:
    return Job(id=i, source="t", title=title, company=company, url=url or f"https://x/{i}", description="d")


def score(i: str, overall_hint: int, dealbreaker: bool = False) -> JobScore:
    return JobScore(job_id=i, skill_fit=overall_hint, seniority_fit=overall_hint, location_fit=overall_hint, growth=overall_hint, dealbreaker_hit=dealbreaker, justification="j")


def test_overall_weights_and_dealbreaker_penalty():
    assert score("a", 5).overall == 5.0
    assert score("a", 0).overall == 0.0
    assert score("a", 5, dealbreaker=True).overall == 3.0
    assert score("a", 1, dealbreaker=True).overall == 0.0  # floored


def test_dedup_by_url_then_title_company():
    a = job("1", "Backend Engineer", "Acme", "https://x/a?utm=1")
    b = job("2", "Backend Engineer", "Acme", "https://x/a")  # same url modulo query string
    c = job("3", "backend engineer", "ACME", "https://x/c")  # same title+company, different url
    d = job("4", "Data Engineer", "Acme", "https://x/d")
    assert [j.id for j in _dedup([a, b, c, d])] == ["1", "4"]


def test_select_top_applies_diversity():
    jobs = [
        job("1", "Senior Backend Engineer", "Acme"),
        job("2", "Backend Engineer", "Acme"),
        job("3", "Lead Backend Engineer", "Acme"),  # third at Acme and third 'backend engineer' -> skipped
        job("4", "AI Engineer", "Beta"),
        job("5", "Platform Engineer", "Gamma"),
    ]
    scores = [score("1", 5), score("2", 5), score("3", 5), score("4", 4), score("5", 3)]
    picked = [j.id for j, _ in select_top(jobs, scores, k=4)]
    assert picked == ["1", "2", "4", "5"]


def test_lexical_prior_prefers_matching_titles():
    from jobad.pipeline.prefilter import rank_pool
    from jobad.schemas import CandidateProfile, SearchQuery, Seniority

    profile = CandidateProfile(
        name="A", headline="Backend engineer moving into AI product engineering", years_experience=9, seniority=Seniority.senior,
        skills=["Python", "FastAPI", "Kafka", "AWS", "LLM"], domains=[], locations_ok=["Berlin"], remote_ok=True, must_haves=[], dealbreakers=[], summary="s",
    )
    queries = [SearchQuery(query="ai engineer", reason="r"), SearchQuery(query="backend engineer python", reason="r")]
    jobs = [
        Job(id="1", source="t", title="Remote Office Assistant", company="X", url="u1", description="python kafka aws llm fastapi " * 10),
        Job(id="2", source="t", title="Senior AI Engineer", company="Y", url="u2", description="Build LLM features in Python with FastAPI on AWS."),
        Job(id="3", source="t", title="Accounts Payable Specialist", company="Z", url="u3", description="Invoices."),
    ]
    ranked = [j.id for j, _ in rank_pool(jobs, profile, queries)]
    assert ranked[0] == "2"
    assert ranked[-1] == "3"


def test_local_bonus_breaks_ties_only():
    tampere = Job(id="t", source="d", title="Backend Engineer", company="Local Oy", url="u1", description="d", location="Tampere, Finland")
    remote = Job(id="r", source="j", title="Backend Developer", company="Remote Inc", url="u2", description="d", location="Remote (Europe)", remote=True)
    better_remote = Job(id="b", source="j", title="Platform Engineer", company="Great Inc", url="u3", description="d", location="Remote (Europe)", remote=True)
    scores = [score("t", 4), score("r", 4), score("b", 5)]
    picked = [j.id for j, _ in select_top([tampere, remote, better_remote], scores, k=3, location="Tampere")]
    assert picked == ["b", "t", "r"]  # clearly better remote job still first; Tampere wins the tie
    assert [j.id for j, _ in select_top([tampere, remote, better_remote], scores, k=3)][1] in ("t", "r")  # no location: no bonus


def test_title_outside_the_candidates_field_is_halved_whatever_the_field():
    from jobad.pipeline.prefilter import lexical_prior

    def prior(title, roles):
        return lexical_prior(Job(id=title, source="t", title=title, company="c", url="u", description="excel"), {"excel"}, set(), set(), roles=roles)

    treasury = {"treasury", "analyst"}
    assert prior("Treasury Analyst", treasury) == 2 * prior("Backend Developer", treasury)
    assert prior("Pääkirjanpitäjä", {"kirjanpitäjä"}) == 2 * prior("Myyntiedustaja", {"kirjanpitäjä"})  # inside a Finnish compound
    assert prior("Ohjelmistokehittäjä", {"kehittäjä"}) == 2 * prior("Kirjanpitäjä", {"kehittäjä"})


def test_role_words_keep_role_nouns_and_drop_seniority():
    from jobad.pipeline.prefilter import role_words
    from jobad.schemas import CandidateProfile, SearchQuery, Seniority

    p = CandidateProfile(name="A", headline="Aspiring Treasury Analyst seeking junior treasury role", years_experience=6, seniority=Seniority.mid, skills=[], domains=[], locations_ok=[], remote_ok=False, must_haves=[], dealbreakers=[], summary="s")
    assert role_words(p, [SearchQuery(query="senior software engineer", reason="r")]) == {"treasury", "analyst", "software", "engineer"}


def test_nothing_below_min_score_is_picked():
    jobs = [job("1", "Treasury Analyst", "A"), job("2", "Backend Developer", "B")]
    picked = [j.id for j, _ in select_top(jobs, [score("1", 3), score("2", 1)], k=4, min_score=2.5)]
    assert picked == ["1"]
    assert select_top(jobs, [score("2", 1)], k=4, min_score=2.5) == []
