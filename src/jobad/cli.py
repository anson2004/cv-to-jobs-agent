"""Command line: profile, plan, run, trace, eval."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from .config import ROOT, Settings

if TYPE_CHECKING:
    from .llm import LLM

app = typer.Typer(add_completion=False, help="One CV in, four reasoned job recommendations out.")
console = Console()
DEFAULT_CV = ROOT / "data" / "cv" / "sample_cv.pdf"
DEFAULT_LABELS = ROOT / "data" / "eval" / "labels.jsonl"


def _llm(run_id: str) -> tuple[Settings, LLM]:
    from .llm import LLM
    from .trace import Tracer

    s = Settings()
    return s, LLM(s, Tracer.for_run(run_id, s.traces_dir))


@app.command()
def profile(cv: Path = typer.Argument(DEFAULT_CV)) -> None:
    """Step 3 only: extract the structured profile from a CV."""
    from .cv import cv_to_text
    from .pipeline.extract import extract_profile

    s, llm = _llm("adhoc-profile")
    p = extract_profile(llm, cv_to_text(cv), s.model_strong)
    console.print_json(p.model_dump_json())


@app.command()
def plan(
    cv: Path = typer.Argument(DEFAULT_CV),
    agentic: bool = typer.Option(False, help="Let the model search with a tool and refine, instead of one blind call."),
    offline: bool = typer.Option(False, help="Searches read the cache only."),
) -> None:
    """Steps 3-4: profile, then the search queries the agent would run."""
    from .cv import cv_to_text
    from .pipeline.extract import extract_profile

    s, llm = _llm("adhoc-plan")
    p = extract_profile(llm, cv_to_text(cv), s.model_strong)
    if agentic:
        from .pipeline.agentic_plan import agentic_plan

        ar = agentic_plan(llm, p, s.model_strong, s.cache_dir, offline)
        console.print(f"{len(ar.searches)} searches over {ar.turns} turns" + ("  (forced submit)" if ar.forced_submit else ""))
        for q_, n in ar.searches:
            console.print(f"  searched '{q_}' -> {n} matches")
        q = ar.plan
    else:
        from .pipeline.plan import plan_queries

        q = plan_queries(llm, p, s.model_strong)
    t = Table("query", "lateral", "reason")
    for x in q.queries:
        t.add_row(x.query, "yes" if x.lateral else "", x.reason)
    console.print(t)
    tot = llm.tracer.summarize(llm.tracer.records).total
    console.print(f"[dim]{tot.calls} llm calls, {tot.prompt_tokens + tot.completion_tokens} tokens[/]")


@app.command()
def run(
    cv: Path = typer.Argument(DEFAULT_CV),
    offline: bool = typer.Option(False, help="Read job sources from cache only."),
    max_jobs: int | None = typer.Option(None, help="Cap on jobs scored (rate limits)."),
    top_k: int | None = typer.Option(None, help="How many recommendations."),
    prompt_version: str = typer.Option("v1", help="Scoring prompt: v1 (default, won the eval) or v2."),
    score_model: str | None = typer.Option(None, help="Override the scoring model."),
    dry_run: bool = typer.Option(False, help="Render the email to disk, do not send, do not mark as sent."),
    include_sent: bool = typer.Option(False, help="Do not filter out previously sent jobs."),
    agentic: bool = typer.Option(False, help="Agentic planning: the model searches with a tool and refines its queries."),
    location: str | None = typer.Option(None, help="Keep only jobs in this city/country or remote-open to it, e.g. 'Tampere'. Also sets Duunitori's area."),
) -> None:
    """Full pipeline: CV -> queries -> fetch -> score -> top-k -> explain -> email."""
    from .pipeline.run import run_pipeline

    run_pipeline(cv, Settings(), offline=offline, max_jobs=max_jobs, top_k=top_k, prompt_version=prompt_version, score_model=score_model, dry_run=dry_run, skip_sent=not include_sent, agentic=agentic, location=location)


@app.command()
def trace(run_id: str) -> None:
    """Where the tokens went: per-step calls, tokens, latency, estimated cost."""
    from .trace import Tracer

    s = Settings()
    path = s.traces_dir / f"{run_id}.jsonl"
    if not path.exists():
        raise typer.BadParameter(f"no trace at {path}")
    summ = Tracer.summarize(Tracer.load(path))
    t = Table("step", "model", "calls", "fail", "prompt tok", "completion tok", "latency s", "est $")
    for step, v in summ.by_step.items():
        t.add_row(step, ", ".join(v.models), str(v.calls), str(v.failures), str(v.prompt_tokens), str(v.completion_tokens), f"{v.latency_s:.1f}", f"{v.est_cost_usd:.5f}")
    tot = summ.total
    t.add_row("[bold]total", "", str(tot.calls), str(tot.failures), str(tot.prompt_tokens), str(tot.completion_tokens), f"{tot.latency_s:.1f}", f"{tot.est_cost_usd:.5f}")
    console.print(t)


@app.command()
def runs() -> None:
    """List past runs."""
    from .schemas import RunStats
    from .store import Store

    st = Store(Settings().db_path)
    t = Table("run_id", "status", "fetched", "deduped", "scored", "delivered")
    for rid, status, summ in st.conn.execute("SELECT run_id, status, summary_json FROM runs ORDER BY started_at DESC"):
        if not summ:  # unfinished run
            t.add_row(rid, status, "", "", "", "")
            continue
        d = RunStats.model_validate_json(summ)
        t.add_row(rid, status, str(d.fetched), str(d.deduped), str(d.scored), d.delivered_to[:60])
    console.print(t)


eval_app = typer.Typer(help="Evaluate the scorer against hand labels.")
app.add_typer(eval_app, name="eval")


@eval_app.command("export")
def eval_export(out: Path = typer.Option(ROOT / "data" / "eval" / "candidates.jsonl"), limit: int = 60) -> None:
    """Dump fetched jobs to a file for hand labelling."""
    from .evals import export_candidates

    n = export_candidates(Settings(), out, limit)
    console.print(f"wrote {n} candidates to {out}. Label them into {DEFAULT_LABELS}.")


@eval_app.command("run")
def eval_run(
    prompt_version: str = typer.Option("v1"),
    model: str | None = typer.Option(None, help="Scoring model; default MODEL_FAST."),
    cv: Path = typer.Option(DEFAULT_CV),
    labels: Path = typer.Option(DEFAULT_LABELS),
    k: int = 4,
) -> None:
    """Score the labelled jobs and report precision@k."""
    from .evals import run_eval

    s = Settings()
    r = run_eval(s, cv, labels, prompt_version=prompt_version, model=model or s.model_fast, k=k)
    console.print_json(r.model_dump_json(exclude={"top_k", "trace"}))
    t = Table("rank", "job_id", "overall", "label")
    for i, x in enumerate(r.top_k, 1):
        t.add_row(str(i), x.job_id, f"{x.overall:.2f}", x.label)
    console.print(t)


@eval_app.command("compare")
def eval_compare(labels: Path = typer.Option(DEFAULT_LABELS)) -> None:
    """Side-by-side table of all saved eval results."""
    from .evals import load_results

    rows = load_results(labels)
    if not rows:
        console.print("no results yet; run `jobad eval run` first")
        raise typer.Exit()
    t = Table("prompt", "model", "n", "P@k", "bad in top-k", "mean good", "mean ok", "mean bad", "separation", "tokens", "est $")
    for r in rows:
        m = r.mean_overall_by_label
        u = r.usage
        t.add_row(r.prompt_version, r.model, str(r.n_scored), f"{r.precision_at_k:.2f}", str(r.bad_in_top_k), str(m["good"]), str(m["ok"]), str(m["bad"]), str(r.separation), str(u.prompt_tokens + u.completion_tokens), f"{u.est_cost_usd:.4f}")
    console.print(t)


if __name__ == "__main__":
    app()
