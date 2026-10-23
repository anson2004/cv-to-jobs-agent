# Job Ad Orchestrator

One CV in, four job recommendations out, by email.

```
CV (pdf) ──▶ extract profile ──▶ plan queries ──▶ fetch + dedup ──▶ prefilter ──▶ score each job
                 [LLM]              [LLM]          [code, cached]     [code]        [LLM ×N]
                                                                                       │
email ◀── fact-check ◀── explain top 4 ◀── select top 4 (max 2 per company) ◀── rank ◀─┘
[code]   [LLM ×4-12]      [LLM]                [code]                     [code]
```

Every model output is validated against a Pydantic schema and retried once on
failure. Scores, ranking and selection are done in code, not by the model.

## Run it

```bash
uv sync
cp .env.example .env               # set GROQ_API_KEY (free at console.groq.com)
uv run python scripts/make_cv.py   # renders the sample CV to PDF

uv run jobad run --dry-run              # sample CV, email written to data/out/<run_id>.html
uv run jobad run --dry-run my_cv.pdf    # your own CV
uv run jobad run my_cv.pdf              # send the email (needs RESEND_API_KEY, TO_EMAIL)
```

Useful options:

| Option | What it does |
|---|---|
| `--max-jobs 10` | Score fewer jobs (default 40) |
| `--location Tampere` | Keep jobs in that place, or remote jobs open to it; on-site jobs ranked a bit higher |
| `--offline` | Read job sources from the local cache only |
| `--no-verify` | Skip the fact-check of the email notes |
| `--agentic` | Let the model search and refine queries in a tool loop (~10× the tokens of the default planner) |

Other commands: `jobad trace <run_id>` (tokens and cost per step),
`jobad runs`, `jobad eval run`, `jobad eval compare`.

## Fact-check agent

The writer agent drafts each job's notes; a checker agent marks every claim
supported or unsupported against the CV and the posting. Unsupported claims go
back to the writer once, the checker looks again, and anything still unsupported
is removed in code (see `src/jobad/pipeline/verify.py`).

Example from a run with the sample CV: 16 claims, 3 flagged. The rewrite
invented "Kafka experience at Freightline" (the CV has Kafka at another job)
and kept "over 3 years of AI work" (the CV shows 18 months); both were dropped.

## Job sources

Arbeitnow, Jobicy and Remotive: public JSON APIs, no key, mostly remote jobs.

Duunitori (Finland) is the only source with Finnish on-site jobs. It is **off
by default** because its `robots.txt` disallows bots; turn it on with
`DUUNITORI_ENABLED=true` for personal use. All responses are cached in `data/cache`.

## Local model (Docker)

```bash
docker compose up -d ollama
OLLAMA_MODEL=qwen3:4b docker compose run --rm pull
```

Then uncomment the "local LLM" block in `.env`. It runs on CPU, so expect about
a minute per scored job.

## GitHub Actions

- **test** — runs `pytest` on every push and PR. No model calls.
- **local-llm-run** — runs the pipeline on Ollama in the runner, Mon and Thu
  05:00 UTC, or by hand from the Actions tab.

Settings for `local-llm-run` (Settings → Secrets and variables → Actions):

| Name | Kind | Purpose |
|---|---|---|
| `CV_URL` | secret | Direct-download link to your CV. Without it, the sample CV is used and the email is uploaded as an artifact |
| `RESEND_API_KEY`, `TO_EMAIL` | secret | Needed when `CV_URL` is set; results are emailed |
| `LOCATION` | variable | e.g. `Tampere` |
| `DUUNITORI_ENABLED` | variable | `true` to include Duunitori |

With `CV_URL` set, nothing about the CV is written to logs, artifacts or cache.

## Configuration

All settings come from environment variables or `.env` (see `.env.example`).
The main ones: `LLM_BASE_URL`, `LLM_API_KEY` (or `GROQ_API_KEY`),
`MODEL_STRONG`, `MODEL_FAST`, `LOCATION`, `DUUNITORI_ENABLED`,
`RESEND_API_KEY`, `TO_EMAIL`. Any OpenAI-compatible endpoint works.

Groq's free tier allows 8K tokens per minute and 200K per day per model, which
is about two full 40-job runs per day.

## Scorer eval

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

Default scorer: qwen3.8-27b with prompt v1 (best P@4, widest good/bad gap, fewest tokens).

## Cost per run

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

Free on Groq; the estimate uses list prices.

## Layout

```
prompts/              versioned prompts
src/jobad/llm.py      the only module that calls a model
src/jobad/schemas.py  the model output contracts
src/jobad/sources/    job APIs, with disk cache
src/jobad/pipeline/   extract, plan, fetch, prefilter, score, select, explain
src/jobad/deliver/    email
src/jobad/evals.py    labelled-set eval
tests/                pure-code tests, no network
```
