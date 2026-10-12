"""Small deterministic text helpers. No LLM here."""

from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v\xa0]+")
_NL = re.compile(r"\n{3,}")
_SENIORITY_WORDS = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "mid", "intern", "head"}
_NOISE = {"of", "the", "a", "an", "and", "&", "-", "–", "/", "(m/w/d)", "(f/m/d)", "(m/f/d)"}


def strip_html(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"</(p|div|li|br|h\d|tr)>", "\n", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _TAG.sub(" ", s)
    s = _WS.sub(" ", s)
    s = "\n".join(line.strip() for line in s.splitlines())
    s = _NL.sub("\n\n", s)
    return s.strip()


def truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def title_stem(title: str) -> str:
    """'Senior Backend Engineer (m/w/d)' -> 'backend engineer'. Used by the diversity rule."""
    words = [w.strip("(),.:").lower() for w in title.split()]
    words = [w for w in words if w and w not in _SENIORITY_WORDS and w not in _NOISE]
    return " ".join(words[:2])


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
