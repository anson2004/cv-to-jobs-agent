# Alex Chen

Berlin, Germany | alex.chen.demo@example.com | github.com/alexchen-demo
Open to: remote (EU time zones) or hybrid in Berlin. Will not relocate outside Germany.

## Summary

Senior backend engineer with 9 years building high-throughput services in Python and Java. For the last 18 months I have led the LLM features of a B2B logistics product: a retrieval-augmented assistant for dispatchers, an evaluation harness that gates prompt changes, and the cost and latency tracing behind it. I want my next role to be an AI product engineer position where I own an LLM-powered feature end to end, from problem framing to evals to shipping.

## Skills

Languages: Python, Java, SQL, TypeScript (working)
Backend: FastAPI, Spring Boot, Kafka, PostgreSQL, Redis, gRPC
LLM / AI: OpenAI and Anthropic APIs, structured outputs and tool calling, retrieval-augmented generation (pgvector), prompt evaluation harnesses, LLM-as-judge grading, token and cost tracing
Cloud / infra: AWS (ECS, Lambda, S3, SQS), Docker, Terraform, GitHub Actions
Practices: product discovery with PMs, A/B experiments, on-call, mentoring

## Experience

### Senior Backend Engineer, Freightline GmbH, Berlin (2022 to present)
- Led a team of three building the "Dispatch Copilot": a RAG assistant over shipment history and carrier contracts, used daily by 400 dispatchers. Cut average lookup time from 6 minutes to under 1.
- Built the evaluation harness: 300 labelled dispatcher questions, automated grading, a CI gate that blocks prompt changes that regress precision. Reduced hallucinated contract terms by 80 percent.
- Designed per-request cost and latency tracing for all LLM calls; brought monthly inference spend down 35 percent by routing simple queries to a smaller model.
- Ran discovery with product managers; wrote the PRDs for two LLM features and killed one after a two-week prototype showed no lift.

### Backend Engineer, Kontomat AG, Berlin (2019 to 2022)
- Owned the payments reconciliation service (Java, Spring Boot, Kafka) processing 2 million events per day.
- Migrated a monolith module to event-driven services on AWS; on-call rotation lead.

### Software Engineer, Nordic Data Oy, Helsinki (2017 to 2019)
- Built data ingestion pipelines in Python for a retail analytics platform. PostgreSQL, Airflow.

## Education

MSc Computer Science, Aalto University, 2017.

## Preferences

Must have: product-facing engineering work, a modern Python or JVM stack, English as the working language, a team that ships LLM features to real users.
Will not consider: crypto, gambling or adtech companies; roles that are on-site only outside Germany; pure consulting or body-leasing; roles with an unpaid trial period.
