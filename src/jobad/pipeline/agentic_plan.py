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
from openai.types.chat import ChatCompletionAssistantMessageParam, ChatCompletionFunctionToolParam
from pydantic import BaseModel, ValidationError

from ..llm import LLM, Messages
from ..prompts import load_prompt
from ..schemas import CandidateProfile, Job, QueryPlan, SearchQuery
from ..sources import ALL_SOURCES, JobSource, build_sources

MAX_SEARCHES = 8
MAX_TURNS = 10
SAMPLE_TITLES = 8

TOOLS: list[ChatCompletionFunctionToolParam] = [
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": "Search the job boards with a short keyword query (1-3 words). Returns the number of matching postings and a sample of titles with companies and locations.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Keyword query in the candidate's field, e.g. 'treasury analyst'"}},
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


class SearchArgs(BaseModel):
    """Arguments of a search_jobs call. submit_plan arguments validate as QueryPlan."""

    query: str = ""


class SearchResult(BaseModel):
    """What search_jobs returns to the model."""

    query: str
    matches: int
    sample: list[str] | None = None
    error: str | None = None

    def to_tool_content(self) -> str:
        return json.dumps(self.model_dump(exclude_none=True))


@dataclass
class AgenticResult:
    plan: QueryPlan
    searches: list[tuple[str, int]] = field(default_factory=list)  # (query, matches)
    turns: int = 0
    forced_submit: bool = False


def _tool_error(message: str) -> str:
    return json.dumps({"error": message})


def _search_tool(sources: list[JobSource], query: str) -> SearchResult:
    jobs: list[Job] = []
    for s in sources:
        try:
            jobs.extend(s.search(query))
        except Exception as e:  # a dead source is reported to the model, not fatal
            return SearchResult(query=query, matches=0, error=f"{s.name} failed: {str(e)[:80]}")
    seen: set[tuple[str, str]] = set()
    sample: list[str] = []
    for j in jobs:
        k = (j.title.lower(), j.company.lower())
        if k in seen:
            continue
        seen.add(k)
        sample.append(f"{j.title} — {j.company} ({j.location or 'n/a'}{', remote' if j.remote else ''})")
        if len(sample) == SAMPLE_TITLES:
            break
    return SearchResult(query=query, matches=len(jobs), sample=sample)


def tool_instructions(max_searches: int) -> str:
    return (
        "\n\nYou have a search_jobs tool. Use it: try a query, look at the matches and sample titles, then refine. "
        f"Broaden queries that return few results; narrow ones that return mostly unrelated roles. Use at most {max_searches} searches, "
        "then call submit_plan with the 4-8 queries that actually surfaced relevant postings. Do not submit a query you did not try."
    )


def agentic_plan(
    llm: LLM,
    profile: CandidateProfile,
    model: str,
    cache_dir: Path,
    offline: bool = False,
    sources: list[JobSource] | None = None,
    *,
    prompt: str = "plan_queries",
    context: str = "",
    max_searches: int | None = None,
    max_turns: int | None = None,
    step: str = "plan_agentic",
) -> AgenticResult:
    """`prompt`, `context` and the budgets let the team planner run this loop as a worker."""
    sources = sources if sources is not None else [S(cache_dir, offline=offline) for S in ALL_SOURCES]
    max_searches = max_searches or MAX_SEARCHES
    max_turns = max_turns or MAX_TURNS
    messages: Messages = [
        {"role": "system", "content": load_prompt(prompt) + tool_instructions(max_searches)},
        {"role": "user", "content": f"Candidate profile:\n{profile.model_dump_json(indent=1)}\n\n{context}Start searching."},
    ]
    searches: list[tuple[str, int]] = []  # (query, matches)
    searches_left = max_searches

    for turn in range(1, max_turns + 1):
        force = searches_left <= 0 or turn == max_turns
        if force:
            # Take the search tool away rather than only forcing tool_choice: Groq
            # rejects the whole request if the model still tries to search.
            messages.append({"role": "user", "content": "Search budget exhausted. Call submit_plan now with the queries that returned relevant postings."})
        try:
            msg = llm.chat_with_tools(
                step=step,
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
            msg = llm.chat_with_tools(step=step, model=model, messages=messages, tools=SUBMIT_ONLY, tool_choice="auto", meta={"turn": turn, "recovery": True})
        calls = [tc for tc in (msg.tool_calls or []) if tc.type == "function"]
        assistant: ChatCompletionAssistantMessageParam = {"role": "assistant", "content": msg.content or ""}
        if calls:
            assistant["tool_calls"] = [{"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in calls]
        messages.append(assistant)

        if not calls:
            # The model talked instead of acting. Nudge once; the turn cap bounds this.
            messages.append({"role": "user", "content": "Use the tools: search_jobs to explore, submit_plan to finish."})
            continue

        for tc in calls:
            name = tc.function.name
            arguments = tc.function.arguments or "{}"
            if name == "search_jobs":
                try:
                    q = SearchArgs.model_validate_json(arguments).query.strip()
                except ValidationError:
                    q = ""
                if searches_left <= 0 or not q:
                    out = _tool_error("search budget exhausted; call submit_plan")
                else:
                    searches_left -= 1
                    found = _search_tool(sources, q)
                    searches.append((q, found.matches))
                    out = found.to_tool_content()
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
            elif name == "submit_plan":
                try:
                    plan = QueryPlan.model_validate_json(arguments)
                except ValidationError as e:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": _tool_error(f"invalid plan: {str(e)[:200]}")})
                    continue
                return AgenticResult(plan=plan, searches=searches, turns=turn, forced_submit=force)
            else:
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": _tool_error(f"unknown tool {name}")})

    # Turn cap hit without a valid submission: fall back to the queries it searched.
    tried = [q for q, n in searches if n > 0] or [q for q, _ in searches]
    plan = QueryPlan(queries=[SearchQuery(query=q, reason="searched by the agent; submit_plan never completed") for q in tried[:8]] or [SearchQuery(query=profile.headline[:40], reason="fallback")])
    return AgenticResult(plan=plan, searches=searches, turns=max_turns, forced_submit=True)
