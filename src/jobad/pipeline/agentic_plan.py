"""Step 4, agentic variant: the model drives the search itself.

Instead of emitting queries blind, the planner gets two tools:
  search_jobs(query)  -> how many postings matched and a sample of titles
  submit_plan(queries) -> the final plan
It searches, looks at what came back, refines or broadens, and submits. Hard
caps keep it bounded: at most MAX_SEARCHES tool calls and MAX_TURNS assistant
turns, after which it is forced to submit. Every search also warms the cache,
so the normal fetch stage afterwards costs no network calls.

Compared with the fixed planner this costs 4-8 model calls instead of 1, and
the queries are chosen with evidence instead of guesses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from openai import BadRequestError

from ..llm import LLM
from ..prompts import load_prompt
from ..schemas import CandidateProfile, QueryPlan, SearchQuery
from ..sources import ALL_SOURCES, JobSource

MAX_SEARCHES = 8
MAX_TURNS = 10
SAMPLE_TITLES = 8

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": "Search the job boards with a short keyword query (2-4 words). Returns the number of matching postings and a sample of titles with companies and locations.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Keyword query, e.g. 'backend engineer python'"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_plan",
            "description": "Submit the final set of 4-8 queries to use, after you have seen search results. Only queries that returned relevant postings belong here.",
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 10,
                        "items": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "reason": {"type": "string", "description": "One sentence: why, citing what the search returned"},
                                "lateral": {"type": "boolean"},
                            },
                            "required": ["query", "reason", "lateral"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["queries"],
                "additionalProperties": False,
            },
        },
    },
]

SUBMIT_ONLY = [t for t in TOOLS if t["function"]["name"] == "submit_plan"]


@dataclass
class AgenticResult:
    plan: QueryPlan | None = None
    searches: list[tuple[str, int]] = field(default_factory=list)  # (query, matches)
    turns: int = 0
    forced_submit: bool = False


def _search_tool(sources: list[JobSource], query: str) -> str:
    jobs = []
    for s in sources:
        try:
            jobs.extend(s.search(query))
        except Exception as e:  # a dead source is reported to the model, not fatal
            jobs_err = f"{s.name} failed: {str(e)[:80]}"
            return json.dumps({"query": query, "matches": 0, "error": jobs_err})
    seen, sample = set(), []
    for j in jobs:
        k = (j.title.lower(), j.company.lower())
        if k in seen:
            continue
        seen.add(k)
        sample.append(f"{j.title} — {j.company} ({j.location or 'n/a'}{', remote' if j.remote else ''})")
        if len(sample) == SAMPLE_TITLES:
            break
    return json.dumps({"query": query, "matches": len(jobs), "sample": sample})


def agentic_plan(llm: LLM, profile: CandidateProfile, model: str, cache_dir: Path, offline: bool = False) -> AgenticResult:
    sources = [S(cache_dir, offline=offline) for S in ALL_SOURCES]
    system = (
        load_prompt("plan_queries")
        + "\n\nYou have a search_jobs tool. Use it: try a query, look at the matches and sample titles, then refine. "
        f"Broaden queries that return few results; narrow ones that return mostly unrelated roles. Use at most {MAX_SEARCHES} searches, "
        "then call submit_plan with the 4-8 queries that actually surfaced relevant postings. Do not submit a query you did not try."
    )
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Candidate profile:\n{profile.model_dump_json(indent=1)}\n\nStart searching."},
    ]
    result = AgenticResult()
    searches_left = MAX_SEARCHES

    for turn in range(1, MAX_TURNS + 1):
        result.turns = turn
        force = searches_left <= 0 or turn == MAX_TURNS
        if force:
            # Take the search tool away rather than only forcing tool_choice: Groq
            # rejects the whole request if the model still tries to search.
            messages.append({"role": "user", "content": "Search budget exhausted. Call submit_plan now with the queries that returned relevant postings."})
        try:
            msg = llm.chat_with_tools(
                step="plan_agentic",
                model=model,
                messages=messages,
                tools=SUBMIT_ONLY if force else TOOLS,
                tool_choice={"type": "function", "function": {"name": "submit_plan"}} if force else "auto",
                meta={"turn": turn, "searches_left": searches_left, "forced": force},
            )
        except BadRequestError as e:
            if "tool_use_failed" not in str(e):
                raise
            # The model emitted a call that did not validate. One more try, submit-only, no forcing.
            msg = llm.chat_with_tools(step="plan_agentic", model=model, messages=messages, tools=SUBMIT_ONLY, tool_choice="auto", meta={"turn": turn, "recovery": True})
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [tc.model_dump() for tc in (msg.tool_calls or [])]} if msg.tool_calls else {"role": "assistant", "content": msg.content or ""})

        if not msg.tool_calls:
            # The model talked instead of acting. Nudge once; the turn cap bounds this.
            messages.append({"role": "user", "content": "Use the tools: search_jobs to explore, submit_plan to finish."})
            continue

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "search_jobs":
                q = str(args.get("query", "")).strip()
                if searches_left <= 0 or not q:
                    out = json.dumps({"error": "search budget exhausted; call submit_plan"})
                else:
                    searches_left -= 1
                    out = _search_tool(sources, q)
                    result.searches.append((q, json.loads(out).get("matches", 0)))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
            elif name == "submit_plan":
                try:
                    plan = QueryPlan(queries=[SearchQuery(**q) for q in args.get("queries", [])])
                except Exception as e:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"error": f"invalid plan: {str(e)[:200]}"})})
                    continue
                result.plan = plan
                result.forced_submit = force
                return result
            else:
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"error": f"unknown tool {name}"})})

    # Turn cap hit without a valid submission: fall back to the queries it searched.
    tried = [q for q, n in result.searches if n > 0] or [q for q, _ in result.searches]
    result.plan = QueryPlan(queries=[SearchQuery(query=q, reason="searched by the agent; submit_plan never completed") for q in tried[:8]] or [SearchQuery(query=profile.headline[:40], reason="fallback")])
    result.forced_submit = True
    return result
