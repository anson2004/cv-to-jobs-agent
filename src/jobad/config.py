"""Settings from environment and .env, validated by pydantic-settings. One place, no magic.

Field names map to upper-case env vars (llm_base_url <- LLM_BASE_URL). Empty
values count as unset, so a blank line in .env falls back to the default.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_ignore_empty=True, extra="ignore")

    # LLM backend (OpenAI-compatible). Groq by default; Ollama or OpenAI by env.
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = Field("ollama", validation_alias=AliasChoices("LLM_API_KEY", "GROQ_API_KEY"))
    model_strong: str = "openai/gpt-oss-120b"
    model_fast: str = "qwen/qwen3.8-27b"  # chosen by eval, see README
    # Force one reasoning effort on every JSON call, e.g. "none" for small local models
    # on CPU, where thinking eats the token budget. Empty = each step's own default.
    # The agentic tool loop keeps its own effort: small models need it to call tools.
    reasoning_effort: str = ""
    llm_timeout_s: float = Field(90, gt=0)  # per request; raise for CPU-only local models

    # Groq free tier per model (checked 2026-10-12): 8K tokens/min, 1K requests/day,
    # and 200K tokens/day. A 40-job run is ~70K tokens, so about two full runs plus
    # one eval per model per day. Spread work across models or wait for the window.
    score_concurrency: int = Field(2, ge=1)
    max_jobs_to_score: int = Field(40, ge=1)
    description_chars: int = Field(1800, ge=100)
    top_k: int = Field(4, ge=1)
    min_score: float = Field(2.5, ge=0, le=5)  # never recommend below this overall score (0-5)

    # Location filter, one place or comma-separated ("Tampere, Helsinki"); empty = no filter. Also selects Duunitori's areas.
    location: str = ""
    # Duunitori is opt-in: undocumented endpoint, robots.txt disallows bots. Personal use only.
    duunitori_enabled: bool = False

    # Delivery
    resend_api_key: str = ""
    to_email: str = ""
    from_email: str = "Job Ad Orchestrator <onboarding@resend.dev>"

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
