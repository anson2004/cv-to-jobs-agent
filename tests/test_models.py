"""Pydantic models at the boundaries: API responses, tool calls, settings, traces. No network, no LLM."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from jobad.config import Settings
from jobad.pipeline.agentic_plan import SearchArgs
from jobad.schemas import QueryPlan
from jobad.sources.jobicy import JobicySource
from jobad.sources.remotive import RemotiveSource
from jobad.trace import Tracer


def test_source_reads_nulls_and_bare_strings_as_empty(tmp_path: Path):
    raw = {"jobs": [{"id": 7, "jobTitle": None, "companyName": " Acme ", "jobType": "full-time", "jobIndustry": None, "pubDate": None}]}
    [job] = JobicySource(tmp_path, offline=True)._parse(raw)
    assert job.id == "jobicy:7" and job.title == "" and job.company == "Acme"
    assert job.tags == ["full-time"] and job.posted_at is None and job.location == "Remote (Anywhere)"


def test_source_rejects_posting_without_id(tmp_path: Path):
    with pytest.raises(ValidationError, match="id"):
        RemotiveSource(tmp_path, offline=True)._parse({"jobs": [{"title": "Backend Engineer"}]})


def test_tool_arguments_validate():
    assert SearchArgs.model_validate_json('{"query": " backend python "}').query == " backend python "
    with pytest.raises(ValidationError):
        SearchArgs.model_validate_json("not json")
    with pytest.raises(ValidationError):
        QueryPlan.model_validate_json('{"queries": [{"query": "a", "reason": "r"}]}')  # fewer than 3


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")  # empty counts as unset
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("SCORE_CONCURRENCY", "3")
    monkeypatch.setenv("DUUNITORI_ENABLED", "yes")
    s = Settings(_env_file=None)
    assert s.llm_api_key == "gsk_test" and s.score_concurrency == 3 and s.duunitori_enabled
    monkeypatch.setenv("SCORE_CONCURRENCY", "0")
    with pytest.raises(ValidationError, match="score_concurrency"):
        Settings(_env_file=None)


def test_trace_round_trip(tmp_path: Path):
    t = Tracer.for_run("r1", tmp_path)
    t.record(step="score_job", model="qwen/qwen3.8-27b", prompt_tokens=100, completion_tokens=20, latency_s=1.23456, ok=True, attempt=1, output={"x": 1})
    t.record(step="score_job", model="qwen/qwen3.8-27b", prompt_tokens=50, completion_tokens=0, latency_s=0.5, ok=False, attempt=2, error="bad json")
    loaded = Tracer.load(t.path)
    assert loaded == t.records
    summary = Tracer.summarize(loaded)
    assert summary.total.calls == 2 and summary.total.failures == 1 and summary.total.prompt_tokens == 150
    assert summary.by_step["score_job"].models == ["qwen/qwen3.8-27b"]
