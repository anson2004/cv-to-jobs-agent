"""The orchestrator. Straight-line pipeline with one adaptive branch.

profile -> plan -> fetch -> (plan_more if thin) -> filter sent -> score ->
select -> explain -> fact-check -> deliver. Each stage prints what it did.
"""

from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from ..config import Settings
from ..cv import cv_to_text
from ..deliver.email import deliver
from ..llm import LLM
from ..schemas import QueryPlan, RunStats, RunSummary
from ..sources import build_sources
from ..store import Store
from ..trace import Tracer
from .explain import explain, notes_only
from .extract import extract_profile
from .fetch import fetch_jobs
from .locate import filter_by_location
from .agentic_plan import agentic_plan
from .team_plan import team_plan
from .plan import plan_more, plan_queries
from .prefilter import rank_pool
from .score import score_jobs
from .select import select_top
from .verify import verify as fact_check

console = Console()
MIN_POOL = 15  # below this, ask the planner for more queries


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def run_pipeline(
    cv_path: Path,
    settings: Settings,
    *,
    offline: bool = False,
    max_jobs: int | None = None,
    top_k: int | None = None,
    prompt_version: str = "v1",
    score_model: str | None = None,
    dry_run: bool = False,
    skip_sent: bool = True,
    agentic: bool = False,
    team: bool = False,
    location: str | None = None,
    verify: bool = True,
) -> RunSummary:
    s = settings
    run_id = new_run_id()
    tracer = Tracer.for_run(run_id, s.traces_dir)
    llm = LLM(s, tracer)
    store = Store(s.db_path)
    store.start_run(run_id)
    max_jobs = max_jobs or s.max_jobs_to_score
    top_k = top_k or s.top_k
    score_model = score_model or s.model_fast
    location = location if location is not None else (s.location or None)
    sources = build_sources(s.cache_dir, offline, duunitori=s.duunitori_enabled, area=location)

    console.rule(f"[bold]run {run_id}")
    console.print(f"[dim]sources: {', '.join(x.name for x in sources)}" + (f"   location filter: {location}" if location else "") + "[/]")

    # 1. CV -> profile
    text = cv_to_text(cv_path)
    profile = extract_profile(llm, text, s.model_strong)
    console.print(f"[green]profile[/] {profile.name}: {profile.headline} ({profile.seniority.value}, {profile.years_experience}y, {len(profile.skills)} skills)")

    # 2. profile -> queries (fixed single call, a team of search agents, or one agent)
    if team:
        tr = team_plan(llm, profile, s.model_strong, s.cache_dir, sources)
        plan = tr.plan
        console.print(f"[green]team plan[/] brief: {', '.join(tr.brief.target_roles)}")
        for w in tr.workers:
            console.print(f"  [green]{w.team}[/] {len(w.searches)} searches, {len(w.queries)} queries" + ("  [yellow](fallback: one call)[/]" if w.fallback else ""))
    elif agentic:
        ar = agentic_plan(llm, profile, s.model_strong, s.cache_dir, offline, sources=sources)
        plan = ar.plan
        console.print(f"[green]agentic plan[/] {len(ar.searches)} searches over {ar.turns} turns" + ("  [yellow](forced submit)[/]" if ar.forced_submit else ""))
        for query, n in ar.searches:
            console.print(f"  [dim]searched[/] '{query}' -> {n} matches")
    else:
        plan = plan_queries(llm, profile, s.model_strong)
    for q in plan.queries:
        console.print(f"  [cyan]{'lateral ' if q.lateral else '        '}[/]'{q.query}'  — {q.reason}")

    # 3. fetch + dedup, with one adaptive round if the pool is thin
    fr = fetch_jobs(plan.queries, s.cache_dir, offline, sources=sources)
    console.print(f"[green]fetch[/] {fr.fetched} raw -> {len(fr.jobs)} after dedup" + ("  [offline]" if offline else ""))
    if len(fr.jobs) < MIN_POOL:
        more = plan_more(llm, profile, fr.per_query, s.model_strong)
        console.print(f"[yellow]thin pool[/] planner added {len(more.queries)} queries: " + ", ".join(f"'{q.query}'" for q in more.queries))
        plan = QueryPlan.model_construct(queries=plan.queries + more.queries)  # merged, may exceed the model's 10
        fr = fetch_jobs(plan.queries, s.cache_dir, offline, sources=sources)
        console.print(f"[green]fetch[/] {fr.fetched} raw -> {len(fr.jobs)} after dedup")
    store.upsert_jobs(run_id, fr.jobs)

    pool = fr.jobs
    if location:
        before = len(pool)
        pool = filter_by_location(pool, location)
        console.print(f"[green]location[/] {before} -> {len(pool)} in or open to {location}")
    if skip_sent:
        sent = store.already_sent()
        before = len(pool)
        pool = [j for j in pool if j.id not in sent]
        if before != len(pool):
            console.print(f"[green]memory[/] skipped {before - len(pool)} already-sent jobs")
    ranked = rank_pool(pool, profile, plan.queries, location=location)
    pool = [j for j, _ in ranked[:max_jobs]]
    if ranked:
        console.print(f"[green]prefilter[/] lexical prior: top {len(pool)} of {len(ranked)} (scores {ranked[0][1]:.1f} … {ranked[min(len(pool), len(ranked)) - 1][1]:.1f}); e.g. '{pool[0].title}' @ {pool[0].company}")

    # 4. score
    console.print(f"[green]score[/] {len(pool)} jobs with {score_model} / prompt {prompt_version} (concurrency {s.score_concurrency})")
    with Progress(transient=True) as prog:
        task = prog.add_task("scoring", total=len(pool))
        scores = score_jobs(
            llm, profile, pool,
            model=score_model, prompt_version=prompt_version,
            concurrency=s.score_concurrency, chars=s.description_chars,
            on_done=lambda: prog.advance(task),
        )
    store.save_scores(run_id, scores, prompt_version, score_model)
    dealbreakers = sum(1 for x in scores if x.dealbreaker_hit)
    console.print(f"  scored {len(scores)}/{len(pool)}; {dealbreakers} dealbreaker hits; best overall {max((x.overall for x in scores), default=0):.2f}")

    # 5. select + explain + fact-check
    picks = select_top(pool, scores, top_k, location=location)
    try:
        recs = explain(llm, profile, picks, s.model_strong)
    except Exception as e:  # the email must still go out with the scorer's own notes
        console.print(f"[yellow]explain failed[/] ({str(e)[:100]}); falling back to scorer justifications")
        recs = [notes_only(j, sc) for j, sc in picks]
    else:
        if verify and picks:
            vr = fact_check(llm, text, picks, recs, s.model_strong)
            recs = vr.recs
            console.print(f"[green]verify[/] {vr.line()}")
    for (j, sc), r in zip(picks, recs):
        console.print(f"[bold]{sc.overall:.2f}[/] {j.title} @ {j.company} [{j.location}]  — {r.one_line_pitch}")

    # 6. deliver + remember
    delivered_to = deliver(s, run_id, profile, picks, recs, dry_run=dry_run)
    if not dry_run:
        store.mark_sent(run_id, [j.id for j, _ in picks])
    console.print(f"[green]deliver[/] {delivered_to}")

    summary = RunSummary(
        run_id=run_id, profile=profile, plan=plan, fetched=fr.fetched, deduped=len(fr.jobs), scored=len(scores),
        top=[(j, sc, r) for (j, sc), r in zip(picks, recs)], delivered_to=delivered_to,
    )
    store.finish_run(run_id, profile, RunStats(fetched=fr.fetched, deduped=len(fr.jobs), scored=len(scores), top=[j.id for j, _ in picks], delivered_to=delivered_to))
    t = tracer.summarize(tracer.records).total
    console.print(f"[dim]llm calls {t.calls}  tokens {t.prompt_tokens}+{t.completion_tokens}  est. cost ${t.est_cost_usd:.4f}  trace data/traces/{run_id}.jsonl[/]")
    return summary
