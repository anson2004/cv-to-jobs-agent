# Job Ad Orchestrator — Build Plan

Demo project: an agentic pipeline that reads one CV, searches the web for jobs,
scores them, and emails the top 4 with reasoning. Built to show AI product
engineering judgment: where the model is used, where it is not, how it is
evaluated, and what it costs.

## Stack (decided)

| Concern | Choice | Why |
|---|---|---|
| LLM | Groq, OpenAI-compatible endpoint | Free tier, fast, JSON mode and tool calling verified |
| Strong model | `openai/gpt-oss-120b` | Profile extraction, query planning, final explanations |
| Fast model | `openai/gpt-oss-20b` | Scoring many jobs under rate limits |
| Alt model | `qwen/qwen3.8-27b` | Second backend for the comparison table |
| Job data | Remotive API + Arbeitnow API | Free, no key, JSON, terms allow API use |
| Email | Resend (fallback: Gmail SMTP app password) | One API call |
| Language | Python 3.13 via `uv` | Fast setup, lockfile |
| Schemas | Pydantic v2 | Validation on every LLM output |
| Storage | SQLite + JSONL traces | No infra, inspectable |
| Local backup LLM | Ollama (M4 Pro, 24 GB) | Never blocked by rate limits |

Groq base URL: `https://api.groq.com/openai/v1`. Key lives in `.env` as
`GROQ_API_KEY`. The OpenAI Python SDK is used as the client, so switching to
Ollama or OpenAI later is a base URL and model name change.

## Where the LLM is used (4 places)

| Step | Call | Model | Input | Output |
|---|---|---|---|---|
| 3 | Profile extraction | 120b | CV text | `CandidateProfile` |
| 4 | Query planning | 120b | profile | 5–8 `SearchQuery` with reasons |
| 6 | Scoring | 20b, one per job | profile + job | `JobScore` |
| 7 | Explanation | 120b | profile + top 4 | `Recommendation` per job |

Everything else is plain code: PDF parsing, fetching, normalising, dedup,
ranking, diversity rule, email rendering, logging, evals.

## Project layout

```
job-ad-orchestrator/
  pyproject.toml
  .env                      # GROQ_API_KEY, RESEND_API_KEY, TO_EMAIL
  PLAN.md
  README.md                 # written last
  data/
    cv/sample_cv.pdf        # synthetic CV
    cache/                  # raw API responses, gitignored
    eval/labels.jsonl       # hand-labelled jobs
  prompts/
    extract_profile.md
    plan_queries.md
    score_job.md            # versioned: v1, v2 for the eval story
    explain.md
  src/jobad/
    schemas.py              # CandidateProfile, Job, SearchQuery, JobScore, Recommendation
    llm.py                  # adapter: complete_json(schema, messages), complete_tools(...)
    cv.py                   # pdf -> text
    sources/
      base.py               # JobSource protocol
      remotive.py
      arbeitnow.py
    pipeline/
      extract.py
      plan.py
      fetch.py              # run queries, cache, normalise, dedup
      score.py              # batched, rate-limited
      select.py             # top-k + diversity
      explain.py
    deliver/email.py
    trace.py                # JSONL logging of every LLM call with tokens + latency
    store.py                # SQLite: runs, jobs, scores, sent
    cli.py                  # `jobad run`, `jobad eval`, `jobad trace <run_id>`
  evals/
    run_eval.py             # precision@4 against labels
  tests/
```

## Schemas (step 1)

**CandidateProfile**: name, headline, years_experience, seniority
(junior|mid|senior|lead), skills (list), domains (list), locations_ok (list),
remote_ok (bool), must_haves (list), dealbreakers (list), summary.

**Job**: id (source + external id), source, title, company, location,
remote (bool), url, description (text, html stripped), tags, posted_at, salary
(optional).

**SearchQuery**: query, reason, lateral (bool).

**JobScore**: job_id, skill_fit (0–5), seniority_fit (0–5), location_fit (0–5),
growth (0–5), overall (computed in code, not by model), justification (1–2
sentences), red_flags (list).

**Recommendation**: job_id, why_you (3 bullets), what_to_address (2 bullets),
one_line_pitch.

## Build steps

Each step ends with something runnable.

1. **Scaffold.** `uv init`, deps: openai, pydantic, pypdf, httpx, typer,
   python-dotenv, resend. Write schemas. Write a synthetic CV as PDF.
2. **Sources + cache.** Implement Remotive and Arbeitnow under one protocol.
   Every response saved to `data/cache/<source>/<query-hash>.json`. A
   `--offline` flag reads cache only. Develop offline from here.
3. **Profile extraction.** `jobad profile data/cv/sample_cv.pdf` prints the
   validated profile. Groq JSON mode + Pydantic validation + one retry on
   failure.
4. **Query planning.** `jobad plan` prints queries with reasons. Prompt asks
   for at least 2 lateral queries.
5. **Fetch + normalise.** Run queries against both sources, map to `Job`,
   strip HTML, dedup by url then by (title, company). Print count before and
   after dedup.
6. **Scoring.** For each job, one 20b call with the rubric prompt. Concurrency
   3–4 with retry on 429. Overall score computed in code as a weighted sum.
   Trace every call.
7. **Select + explain.** Top 4 by overall with a diversity rule: max 2 per
   company, max 3 with the same title stem. One 120b call writes
   recommendations.
8. **Deliver.** Render HTML email from a template, send via Resend. Record
   sent job ids in SQLite so a rerun never resends.
9. **Tracing.** `jobad trace <run_id>` prints per-step token counts, latency,
   and estimated cost at list prices (zero on Groq free tier, but the
   accounting is the point).
10. **Evals.** Label 20–30 cached jobs as good/ok/bad against the synthetic CV.
    `jobad eval` reports precision@4 and mean score by label. Write
    `score_job v2` prompt, rerun, show the delta. Also run with the qwen
    model for a backend comparison row.
11. **README.** Architecture diagram, LLM vs code split, design decisions and
    rejected options, eval table, cost table, how to run.

## Groq-specific notes

- Free tier is rate-limited per model. Check Settings → Limits before step 6
  and set concurrency accordingly. Scoring 50 jobs at ~1.5K tokens each is
  ~75K tokens per run.
- Use `response_format={"type":"json_object"}` plus the schema in the prompt.
  Validate with Pydantic. If a model supports `json_schema` mode use it, but
  do not depend on it.
- gpt-oss models return reasoning in a separate field. Ignore it, but log it
  in traces, it is a nice thing to show.
- On 429, back off and retry. On repeated 429, fall back to Ollama if
  configured.

## Demo script (5 minutes)

1. Show the synthetic CV. Run `jobad run --offline`.
2. Watch profile, queries, fetch counts, scoring progress, top 4.
3. Open the email.
4. `jobad trace <run_id>`: where the tokens went.
5. `jobad eval`: precision@4 for prompt v1 vs v2, and 20b vs qwen.
6. Open README: the LLM/code split and the rejected options.

## Explicitly out of scope (mention in README as next steps)

Scheduling, feedback loop, memory across weeks, WhatsApp, scraping
LinkedIn/Indeed, a web UI.

## Estimated effort

| Day | Steps |
|---|---|
| 1 | 1–5: pipeline through fetch, offline-capable |
| 2 | 6–9: scoring, selection, email, traces |
| 3 | 10–11: evals, README, polish |

## Decision: no agent framework

No LangChain, LangGraph or similar. Four structured LLM calls and one small
tool loop do not need an abstraction layer, every line should be explainable
in an interview, and Groq quirks (rate limits, reasoning field, JSON mode)
are simpler to handle directly. The README gets a short "Why no framework"
paragraph saying this.

## Findings during the build (2026-10-12)

- Remotive and Arbeitnow ignore their `search` parameter; both are modelled as
  feeds with local keyword filtering. Jobicy added as the real search source.
- A lexical prefilter (code) chooses which 40 of ~600 postings get a model
  call. Hit-count ordering was actively harmful with feed sources.
- Groq `json_object` mode 400s with `json_validate_failed` when the model
  spends its budget reasoning; adapter retries without JSON mode.
- Qwen3 on Groq needs `reasoning_effort: none` and `reasoning_format: hidden`
  or its chain of thought lands in `content`.
- Scoring calls trimmed from ~1,700 to ~900 tokens by stripping schema
  descriptions from the hint (the prompt already explains the fields).
- Eval outcome: Qwen 27B + prompt v1 is the best scorer (P@4 0.75, good−bad
  gap 3.0, fewest tokens); v2 calibration rules did not help; gpt-oss-120b is
  the weakest ranker. Defaults changed accordingly. 20b hit the 200K
  tokens-per-day cap before v2 could be measured on it.
