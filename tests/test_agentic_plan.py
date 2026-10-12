"""The agentic planner with a fake model: search, read results, submit. No network, no LLM."""

import json
from types import SimpleNamespace

from jobad.pipeline import agentic_plan as ap
from jobad.schemas import CandidateProfile, Job, Seniority


class FakeSource:
    name = "fake"
    kind = "search"

    def __init__(self, *a, **k):
        pass

    def search(self, query):
        n = 3 if "python" in query else 0
        return [Job(id=f"f:{query}:{i}", source="fake", title=f"{query} role {i}", company="Co", url=f"u{i}", description="d") for i in range(n)]


def _call(name, args, cid):
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=json.dumps(args)), model_dump=lambda: {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}})


class FakeLLM:
    """Turn 1: search two queries. Turn 2: submit only the one that matched."""

    def __init__(self):
        self.turn = 0
        self.seen_tool_results = []

    def chat_with_tools(self, *, messages, tool_choice, **kw):
        self.turn += 1
        self.seen_tool_results += [m["content"] for m in messages if m.get("role") == "tool"]
        if self.turn == 1:
            return SimpleNamespace(content="", tool_calls=[_call("search_jobs", {"query": "backend python"}, "a"), _call("search_jobs", {"query": "golang"}, "b")])
        return SimpleNamespace(content="", tool_calls=[_call("submit_plan", {"queries": [{"query": "backend python", "reason": "3 matches", "lateral": False}, {"query": "python platform", "reason": "adjacent", "lateral": True}, {"query": "ai python", "reason": "target", "lateral": False}]}, "c")])


def test_agent_searches_then_submits(monkeypatch, tmp_path):
    monkeypatch.setattr(ap, "ALL_SOURCES", [FakeSource])
    profile = CandidateProfile(name="A", headline="h", years_experience=5, seniority=Seniority.senior, skills=["Python"], domains=[], locations_ok=["Berlin"], remote_ok=True, must_haves=[], dealbreakers=[], summary="s")
    llm = FakeLLM()
    res = ap.agentic_plan(llm, profile, "fake-model", tmp_path)
    assert res.turns == 2 and not res.forced_submit
    assert res.searches == [("backend python", 3), ("golang", 0)]
    assert [q.query for q in res.plan.queries][0] == "backend python"
    # the model saw the search results before submitting
    assert any('"matches": 3' in r for r in llm.seen_tool_results)


def test_agent_is_forced_to_submit_when_budget_is_gone(monkeypatch, tmp_path):
    monkeypatch.setattr(ap, "ALL_SOURCES", [FakeSource])
    monkeypatch.setattr(ap, "MAX_SEARCHES", 1)

    class Stubborn(FakeLLM):
        def chat_with_tools(self, *, messages, tool_choice, **kw):
            self.turn += 1
            if tool_choice != "auto":  # forced: must submit
                return SimpleNamespace(content="", tool_calls=[_call("submit_plan", {"queries": [{"query": "backend python", "reason": "r", "lateral": False}] * 3}, "z")])
            return SimpleNamespace(content="", tool_calls=[_call("search_jobs", {"query": "backend python"}, f"s{self.turn}")])

    profile = CandidateProfile(name="A", headline="h", years_experience=5, seniority=Seniority.senior, skills=["Python"], domains=[], locations_ok=[], remote_ok=True, must_haves=[], dealbreakers=[], summary="s")
    res = ap.agentic_plan(Stubborn(), profile, "fake-model", tmp_path)
    assert res.forced_submit and len(res.searches) == 1 and len(res.plan.queries) == 3
