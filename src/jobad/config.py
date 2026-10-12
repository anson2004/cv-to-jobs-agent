"""Settings from environment. One place, no magic."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    # LLM backend (OpenAI-compatible). Groq by default; Ollama or OpenAI by env.
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "https://api.groq.com/openai/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY") or _env("GROQ_API_KEY") or "ollama")
    model_strong: str = field(default_factory=lambda: _env("MODEL_STRONG", "openai/gpt-oss-120b"))
    model_fast: str = field(default_factory=lambda: _env("MODEL_FAST", "qwen/qwen3.8-27b"))  # chosen by eval, see README

    # Groq free tier per model (checked 2026-10-12): 8K tokens/min, 1K requests/day,
    # and 200K tokens/day. A 40-job run is ~70K tokens, so about two full runs plus
    # one eval per model per day. Spread work across models or wait for the window.
    score_concurrency: int = field(default_factory=lambda: int(_env("SCORE_CONCURRENCY", "2")))
    max_jobs_to_score: int = field(default_factory=lambda: int(_env("MAX_JOBS_TO_SCORE", "40")))
    description_chars: int = field(default_factory=lambda: int(_env("DESCRIPTION_CHARS", "1800")))
    top_k: int = 4

    # Location filter (e.g. "Tampere"); empty = no filter. Also selects Duunitori's area.
    location: str = field(default_factory=lambda: _env("LOCATION"))
    # Duunitori is opt-in: undocumented endpoint, robots.txt disallows bots. Personal use only.
    duunitori_enabled: bool = field(default_factory=lambda: _env("DUUNITORI_ENABLED", "false").lower() in ("1", "true", "yes"))

    # Delivery
    resend_api_key: str = field(default_factory=lambda: _env("RESEND_API_KEY"))
    to_email: str = field(default_factory=lambda: _env("TO_EMAIL"))
    from_email: str = field(default_factory=lambda: _env("FROM_EMAIL", "Job Ad Orchestrator <onboarding@resend.dev>"))

    # Paths
    data_dir: Path = ROOT / "data"
    prompts_dir: Path = ROOT / "prompts"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def traces_dir(self) -> Path:
        return self.data_dir / "traces"

    @property
    def out_dir(self) -> Path:
        return self.data_dir / "out"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobad.sqlite"


# Estimated list prices per 1M tokens (input, output), USD. Groq free tier
# charges nothing; these exist so cost accounting is real when the backend
# changes. Update when you change providers.
LIST_PRICES: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "qwen/qwen3.8-27b": (0.20, 0.60),
}
