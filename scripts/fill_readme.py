"""Fill the README's eval and cost tables from data/eval/results and a run trace.

Usage: uv run python scripts/fill_readme.py <run_id>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobad.evals import load_results  # noqa: E402
from jobad.trace import Tracer  # noqa: E402


def eval_table() -> str:
    rows = load_results(ROOT / "data/eval/labels.jsonl")
    rows.sort(key=lambda r: (r.model, r.prompt_version))
    out = ["| prompt | model | scored | P@4 | bad in top 4 | mean good | mean ok | mean bad | good − bad | tokens |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        m = r.mean_overall_by_label
        u = r.usage
        partial = " ⚠" if r.n_scored < r.n_labelled else ""
        out.append(f"| {r.prompt_version} | {r.model.split('/')[-1]} | {r.n_scored}/{r.n_labelled}{partial} | {r.precision_at_k:.2f} | {r.bad_in_top_k} | {m['good']} | {m['ok']} | {m['bad']} | {r.separation} | {u.prompt_tokens + u.completion_tokens:,} |")
    n = rows[0].n_labelled if rows else 0
    return f"{n} hand-labelled jobs, 5 good / 10 ok / 19 bad. P@4 = share of the scorer's top four labelled good.\n\n" + "\n".join(out)


def cost_table(run_id: str) -> str:
    recs = Tracer.load(ROOT / "data/traces" / f"{run_id}.jsonl")
    s = Tracer.summarize(recs)
    out = ["| step | model | calls | prompt tokens | completion tokens | est. cost at list price |", "|---|---|---|---|---|---|"]
    for step, v in s.by_step.items():
        out.append(f"| {step} | {', '.join(x.split('/')[-1] for x in v.models)} | {v.calls} | {v.prompt_tokens:,} | {v.completion_tokens:,} | ${v.est_cost_usd:.4f} |")
    t = s.total
    out.append(f"| **total** | | {t.calls} | {t.prompt_tokens:,} | {t.completion_tokens:,} | **${t.est_cost_usd:.4f}** |")
    return f"One full run (`{run_id}`), 40 jobs scored:\n\n" + "\n".join(out)


def main(run_id: str) -> None:
    p = ROOT / "README.md"
    s = p.read_text()
    s = re.sub(r"<!-- EVAL_TABLE -->.*?<!-- /EVAL_TABLE -->", f"<!-- EVAL_TABLE -->\n{eval_table()}\n<!-- /EVAL_TABLE -->", s, flags=re.S)
    s = re.sub(r"<!-- COST_TABLE -->.*?<!-- /COST_TABLE -->", f"<!-- COST_TABLE -->\n{cost_table(run_id)}\n<!-- /COST_TABLE -->", s, flags=re.S)
    p.write_text(s)
    print("README tables filled")


if __name__ == "__main__":
    main(sys.argv[1])
