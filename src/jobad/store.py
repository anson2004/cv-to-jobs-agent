"""SQLite persistence: runs, jobs seen, scores, and what has been sent.

The 'sent' table is what stops a rerun from recommending the same job twice.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .schemas import CandidateProfile, Job, JobScore

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, started_at REAL, status TEXT, profile_json TEXT, summary_json TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY, first_seen_run TEXT, json TEXT
);
CREATE TABLE IF NOT EXISTS scores (
  run_id TEXT, job_id TEXT, prompt_version TEXT, model TEXT, json TEXT,
  PRIMARY KEY (run_id, job_id)
);
CREATE TABLE IF NOT EXISTS sent (
  job_id TEXT PRIMARY KEY, run_id TEXT, sent_at REAL
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def start_run(self, run_id: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO runs(run_id, started_at, status) VALUES (?,?,?)", (run_id, time.time(), "started"))
        self.conn.commit()

    def finish_run(self, run_id: str, profile: CandidateProfile, summary: dict) -> None:
        self.conn.execute(
            "UPDATE runs SET status=?, profile_json=?, summary_json=? WHERE run_id=?",
            ("done", profile.model_dump_json(), json.dumps(summary, default=str), run_id),
        )
        self.conn.commit()

    def upsert_jobs(self, run_id: str, jobs: list[Job]) -> None:
        self.conn.executemany(
            "INSERT OR IGNORE INTO jobs(job_id, first_seen_run, json) VALUES (?,?,?)",
            [(j.id, run_id, j.model_dump_json()) for j in jobs],
        )
        self.conn.commit()

    def save_scores(self, run_id: str, scores: list[JobScore], prompt_version: str, model: str) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO scores(run_id, job_id, prompt_version, model, json) VALUES (?,?,?,?,?)",
            [(run_id, s.job_id, prompt_version, model, s.model_dump_json()) for s in scores],
        )
        self.conn.commit()

    def already_sent(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT job_id FROM sent")}

    def mark_sent(self, run_id: str, job_ids: list[str]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO sent(job_id, run_id, sent_at) VALUES (?,?,?)",
            [(j, run_id, time.time()) for j in job_ids],
        )
        self.conn.commit()

    def get_job(self, job_id: str) -> Job | None:
        row = self.conn.execute("SELECT json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def all_jobs(self) -> list[Job]:
        return [Job.model_validate_json(r[0]) for r in self.conn.execute("SELECT json FROM jobs")]
