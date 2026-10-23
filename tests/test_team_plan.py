"""The team planner with a fake model and fake boards, plus query routing and Finnish titles. No network, no LLM."""

import json
from types import SimpleNamespace

from jobad.pipeline import team_plan as tp
from jobad.pipeline.fetch import fetch_jobs
from jobad.pipeline.prefilter import lexical_prior
from jobad.schemas import CandidateProfile, Job, QueryPlan, SearchBrief, SearchQuery, Seniority
from jobad.sources import query_terms

PROFILE = CandidateProfile(name="A", headline="Backend engineer", years_experience=5, seniority=Seniority.senior, skills=["Python"], domains=[], locations_ok=["Tampere"], remote_ok=True, must_haves=[], dealbreakers=[], summary="s")
BRIEF = SearchBrief(target_roles=["backend engineer", "platform engineer"], notes="n")


class FakeSource:
    kind = "search"

    def __init__(self, name):
        self.name = name
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return [Job(id=f"{self.name}:{query}", source=self.name, title=f"{query} role", company=self.name, url=f"u/{self.name}/{query}", description="d")]


def _call(name, args, cid):
    return SimpleNamespace(id=cid, type="function", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _plan(*queries):
    return {"queries": [{"query": q, "reason": "r", "lateral": False} for q in queries]}


class FakeLLM:
    """Coordinator writes BRIEF. The remote worker searches then submits; the Finnish worker cannot use tools."""

    def __init__(self):
        self.steps = []

    def complete_json(self, schema, *, step, user, **kw):
        self.steps.append(step)
        if schema is SearchBrief:
            return BRIEF
        assert step == "plan_team:finland:fallback" and "duunitori" in user
        return QueryPlan.model_validate(_plan("ohjelmistokehittäjä", "backend-kehittäjä", "python"))

    def chat_with_tools(self, *, step, messages, **kw):
        self.steps.append(step)
        if step == "plan_team:finland":
            raise RuntimeError("model does not call tools")
        assert "backend engineer" in messages[1]["content"]  # the brief reached the worker
        if not any(m.get("role") == "tool" for m in messages):
            return SimpleNamespace(content="", tool_calls=[_call("search_jobs", {"query": "backend python"}, "a")])
        return SimpleNamespace(content="", tool_calls=[_call("submit_plan", _plan("backend python", "platform engineer", "python api"), "b")])


def test_coordinator_briefs_workers_and_code_routes_their_queries(tmp_path):
    remote, fi = FakeSource("jobicy"), FakeSource("duunitori")
    res = tp.team_plan(FakeLLM(), PROFILE, "m", tmp_path, [remote, fi])
    by_team = {w.team: w for w in res.workers}
    assert by_team["remote boards"].searches == [("backend python", 1)] and not by_team["remote boards"].fallback
    assert by_team["finland"].fallback  # tool loop failed, one plain call instead
    assert {q.query: q.sources for q in res.plan.queries} == {
        "backend python": ["jobicy"], "platform engineer": ["jobicy"], "python api": ["jobicy"],
        "ohjelmistokehittäjä": ["duunitori"], "backend-kehittäjä": ["duunitori"], "python": ["duunitori"],
    }
    assert fi.queries == []  # the remote worker never searched the Finnish board


def test_fetch_runs_each_query_only_on_its_sources(tmp_path):
    a, b = FakeSource("jobicy"), FakeSource("duunitori")
    queries = [SearchQuery(query="python", reason="r", sources=["duunitori"]), SearchQuery(query="golang", reason="r")]
    fetch_jobs(queries, tmp_path, True, sources=[a, b])
    assert a.queries == ["golang"] and b.queries == ["python", "golang"]


def test_no_duunitori_means_one_team():
    assert [t.name for t in tp.build_teams([FakeSource("jobicy"), FakeSource("remotive")])] == ["remote boards"]


def test_finnish_words_survive_tokenizing_and_count_as_engineering():
    assert query_terms("backend-kehittäjä python") == ["backend-kehittäjä", "python"]
    fi = Job(id="d:1", source="duunitori", title="Ohjelmistokehittäjä", company="C", url="u", description="Python")
    sales = Job(id="d:2", source="duunitori", title="Myyntiedustaja", company="C", url="u2", description="Python")
    # same description; only the Finnish engineering title escapes the non-engineering halving
    assert lexical_prior(fi, {"python"}, set(), set()) == 2 * lexical_prior(sales, {"python"}, set(), set())
