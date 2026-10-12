# Job Ad Orchestrator

One CV in, four reasoned job recommendations out.

A small agentic pipeline built to show AI product engineering judgment: where a
language model is used and where it is not, how outputs are validated, how the
scorer is evaluated, and what each run costs. It runs on Groq's free tier and
two keyless job APIs, so anyone can clone it and run it.

```
CV (pdf) ──▶ extract profile ──▶ plan queries ──▶ fetch + dedup ──▶ prefilter ──▶ score each job
                 [LLM]              [LLM]          [code, cached]     [code]        [LLM ×N]
                                       ▲                                   │
                                       └── plan more if pool is thin ◀─────┤
                                                                           ▼
            email ◀── explain top 4 ◀── select top 4 (diversity rule) ◀── rank
           [code]        [LLM]                 [code]                    [code]
```

## Where the model is used, and where it is not

| Stage | LLM? | Model | Why |
|---|---|---|---|
| CV → structured profile | yes | gpt-oss-120b | Reading prose into a schema is what models are for |
| Profile → search queries | yes | gpt-oss-120b | Needs judgment about adjacent roles the candidate would not search for |
| Fetch, normalise, dedup | no | | Deterministic, cacheable, free |
| Lexical prefilter: which 40 of 600+ get a model call | no | | A testable heuristic beats spending tokens on office-assistant postings |
| Score each job (4 dimensions) | yes | qwen3.8-27b | Fuzzy judgment, but a small model because it runs N times; chosen by the eval below |
| Overall score, ranking, top-4 with diversity | no | | Arithmetic and rules belong in code, where they are testable |
| Write "why you" / "what to address" | yes | gpt-oss-120b | Explanation quality matters most here |
| Render and send the email | no | | |
| Remember what was sent | no | SQLite | A rerun never recommends the same job twice |

Every model output is validated against a Pydantic schema. On a validation
failure the error is fed back to the model once. The model never computes the
overall score and never chooses the job id; code does.

## Run it

```bash
uv sync
cp .env.example .env            # or just set GROQ_API_KEY
uv run python scripts/make_cv.py   # renders the synthetic CV to PDF

uv run jobad run --dry-run      # full pipeline, email written to data/out/<run_id>.html
uv run jobad run --offline      # same, but job sources read from cache only
uv run jobad trace <run_id>     # tokens, latency, estimated cost per step
uv run jobad eval compare       # scorer quality across prompt versions and models
```

Groq free tier is 8K tokens per minute and 200K tokens per day, per model,
so a run that scores 40 jobs takes a few minutes and you get roughly two
full runs plus one eval per model per day. `--max-jobs` caps it; `MODEL_FAST`
and `MODEL_STRONG` in `.env` move work to a different model's budget. To send real email set
`RESEND_API_KEY` and `TO_EMAIL` in `.env` and drop `--dry-run`.

## Evaluation

The scorer is the only part whose quality is hard to see by eye, so it has an
eval. Jobs fetched for the synthetic CV were hand-labelled good / ok / bad.
`jobad eval run` scores them and reports precision at 4 (how many of the
scorer's top four are labelled good), how many bad jobs leak into the top four,
and the gap between mean scores of good and bad jobs.

<!-- EVAL_TABLE -->
34 hand-labelled jobs, 5 good / 10 ok / 19 bad. P@4 = share of the scorer's top four labelled good.

| prompt | model | scored | P@4 | bad in top 4 | mean good | mean ok | mean bad | good − bad | tokens |
|---|---|---|---|---|---|---|---|---|---|
| v1 | gpt-oss-120b | 34/34 | 0.50 | 0 | 3.82 | 3.32 | 2.12 | 1.7 | 42,970 |
| v2 | gpt-oss-120b | 34/34 | 0.50 | 0 | 3.77 | 3.49 | 1.8 | 1.97 | 56,077 |
| v1 | gpt-oss-20b | 34/34 | 0.75 | 0 | 3.47 | 2.64 | 1.67 | 1.8 | 41,442 |
| v1 | qwen3.8-27b | 34/34 | 0.75 | 0 | 4.02 | 2.15 | 0.99 | 3.03 | 38,618 |
| v2 | qwen3.8-27b | 34/34 | 0.75 | 0 | 3.15 | 1.42 | 0.66 | 2.49 | 48,778 |
<!-- /EVAL_TABLE -->

What the table says, and what changed because of it:

- **No configuration let a bad job into the top four.** The dealbreaker flag
  and the location dimension do most of that work.
- **The small Qwen model with the plain v1 prompt is the best ranker here**:
  highest precision, the widest gap between good and bad jobs, and the fewest
  tokens. It is now the default scoring model, and v1 the default prompt.
- **Prompt v2, which adds explicit calibration rules, did not earn its
  tokens.** On Qwen it narrowed the good/bad gap; on gpt-oss-120b it widened
  it slightly but left precision unchanged and cost 30% more. The rules were
  written from intuition; the eval said no. It stays in the repo as the
  worked example of a prompt change that was measured and rejected.
- **The biggest model is the weakest ranker.** gpt-oss-120b scores "ok" jobs
  almost as high as good ones. For a rubric-scoring task a smaller model that
  follows the rubric literally does better than a larger one that reasons
  around it.
- **Missing row:** v2 on gpt-oss-20b could not be completed on the day of
  measurement. Groq's free tier also has a 200K tokens-per-day cap per model,
  found the hard way after three pipeline runs and one eval on that model.

Caveat: 5 good jobs among 34 labels is a small set. The gaps between
configurations are suggestive, not conclusive; the point is that the
project measures rather than assumes.

## Cost and tokens

<!-- COST_TABLE -->
One full run (`20261012-124644`), 40 jobs scored:

| step | model | calls | prompt tokens | completion tokens | est. cost at list price |
|---|---|---|---|---|---|
| extract_profile | gpt-oss-120b | 1 | 1,121 | 801 | $0.0006 |
| plan_queries | gpt-oss-120b | 1 | 765 | 653 | $0.0005 |
| score_job | gpt-oss-20b | 40 | 50,183 | 11,224 | $0.0071 |
| explain | gpt-oss-120b | 1 | 2,368 | 772 | $0.0008 |
| **total** | | 43 | 54,437 | 13,450 | **$0.0091** |
<!-- /COST_TABLE -->

Groq's free tier charges nothing. The estimate uses list prices so the
accounting is real if the backend changes. Any OpenAI-compatible endpoint works:
set `LLM_BASE_URL`, `LLM_API_KEY`, `MODEL_STRONG`, `MODEL_FAST` in `.env`
(Ollama settings are shown as comments there).

## Design decisions

**No scraping.** LinkedIn and Indeed forbid it and break scrapers without
notice. Remotive and Arbeitnow are public JSON APIs with no key. A demo that
can break the morning it is shown is not a demo. Every API response is cached
so the pipeline also runs fully offline.

**Feeds are not search engines.** Remotive and Arbeitnow accept a `search`
parameter and ignore it: every query returned the identical set (verified by
diffing cached responses). Pretending otherwise would make the planner's
queries decorative. So those two are modelled as *feed* sources, fetched once
per run, with the planned queries applied locally as all-terms keyword
filters, and Jobicy, whose `tag=` filter really works, is the *search* source.
The planner's queries still decide what enters the pool.

**A lexical prior before the model.** 600+ unique postings come back per run
and the free tier allows about 40 model calls in a few minutes. Which 40?
Not "the ones most queries hit": with feed sources that rewards the
postings the APIs return regardless of query (office assistants, copywriters).
Instead a small, unit-tested lexical score ranks the pool by overlap between
the candidate's skills and target-role words and each posting's title, tags
and body, plus a location bonus. Every hand-labelled good job lands in the
top 40 under that prior; three in the top 10.

**No agent framework.** Four structured calls and one adaptive branch do not
need LangChain or LangGraph. Hand-written, the whole model boundary is one file
(`src/jobad/llm.py`, ~150 lines) and every retry and validation step is visible.
A framework would add abstractions to explain without adding capability here.

**Small model for the N-times call, big model for the one-time calls.** Scoring
runs once per job, so it uses a small model with reasoning off and a
truncated description. Extraction, planning and explanation run once per run
and get the 120b model. The eval picked which small model.

**Diversity rule in code, not in the prompt.** A pure sort by score returns
four near-identical postings. At most two per company and two per title stem
fixes that deterministically, and it is unit tested.

**One adaptive branch, not a free-running loop.** If the first round of
queries yields fewer than 15 unique jobs, the planner sees what it tried and
the counts, and proposes three different queries. That is the agentic moment
worth having; an open-ended loop would cost more and be harder to make
reliable.

**Rejected:** WhatsApp delivery (Twilio template approval for no demo value),
a web UI, scheduling and a feedback loop (real product features, out of scope
for a demo), embeddings for retrieval (keyword APIs cannot use them; the
scorer already reads full descriptions).

## Layout

```
prompts/              versioned prompt files (score_job_v1.md, score_job_v2.md, …)
src/jobad/llm.py      the only module that calls a model
src/jobad/schemas.py  every contract the model must satisfy
src/jobad/sources/    job APIs behind one protocol, with disk cache
src/jobad/pipeline/   extract, plan, fetch, score, select, explain, run
src/jobad/deliver/    email template and sender
src/jobad/evals.py    labelled-set evaluation
data/traces/          one JSONL per run, one line per model call
data/eval/            labels.jsonl and results/
tests/                the pure-code parts: scoring arithmetic, dedup, diversity
```

## Next steps if this were a product

Weekly scheduled runs, a reply-to-refine loop ("more like this", "not this")
that updates the profile, per-user profiles, a job source adapter for company
career pages, and an LLM-as-judge eval to scale labelling past what one person
can hand-label.
