"""Prompts live as markdown files under prompts/ so they are diffable and versioned."""

from __future__ import annotations

from functools import lru_cache

from .config import Settings


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    path = Settings().prompts_dir / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path.read_text()
