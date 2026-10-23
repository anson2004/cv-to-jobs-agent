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
| `--team` | Plan with a coordinator and one search agent per group of boards (see below) |
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

## Search team (`--team`)

A coordinator agent writes a brief (target roles, roles to avoid). Two search
agents work from it in parallel, each on its own boards and with its own
prompt: one searches the remote boards in English, one searches Duunitori in
Finnish and English. Code tags each query with its agent's boards, so fetch runs
it only there (`src/jobad/pipeline/team_plan.py`). An agent that cannot drive
its tools falls back to a single planning call.

Measured with the sample CV, `--location Tampere` and Duunitori on: the team put
6 Tampere jobs in the 15 that get scored, the same as the default planner. The
reason is that Duunitori is a feed: every run already sweeps all ~130 Tampere
tech postings, so query language barely changes the pool. It stays opt-in.
What did help was ranking Finnish titles ("ohjelmistokehittäjä") as
engineering roles in the prefilter: 5 → 6 Tampere jobs, for every planner.

## Job sources

Arbeitnow, Jobicy and Remotive: public JSON APIs, no key, mostly remote tech jobs.

Duunitori (Finland) covers every field and is the only source with Finnish
on-site jobs. It is searched with the planner's queries, so with the words of
the candidate's own field (for an accountant: "kirjanpitäjä", "treasury
analyst"). It is **off by default** because its `robots.txt` disallows bots;
turn it on with `DUUNITORI_ENABLED=true` for personal use. For a CV outside
tech, nearly all good matches come from Duunitori. All responses are cached in
`data/cache`.

Nothing in the pipeline assumes a field: the prompts, the prefilter and the
sources work from the CV. Jobs scoring below `MIN_SCORE` (default 2.5/5) are
never recommended; if none reach it, the email says there was no good match.

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
| `DEBUG_LOGS` | variable | `true` prints the scored jobs (titles and scores, no CV text) in the log |
| `LOG_KEY` | secret | With `DEBUG_LOGS`, uploads the full run log, traces and email as an encrypted `run-log` artifact (kept 7 days) |

With `CV_URL` set, nothing about the CV is written to logs, artifacts or cache
unless encrypted. To read the debug artifact, download `run-log` from the run's
Summary page (or `gh run download <run-id> -n run-log`), then:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -in run-log.enc -out run-log.tar.gz -pass pass:'<LOG_KEY>'
tar xzf run-log.tar.gz   # run.log, traces/<run_id>.jsonl (every model call), out/ (email, jobs report)
```

## Configuration

All settings come from environment variables or `.env` (see `.env.example`).
The main ones: `LLM_BASE_URL`, `LLM_API_KEY` (or `GROQ_API_KEY`),
`MODEL_STRONG`, `MODEL_FAST`, `LOCATION`, `DUUNITORI_ENABLED`, `MIN_SCORE`,
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
