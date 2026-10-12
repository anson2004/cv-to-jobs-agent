"""CV file to plain text. PDF via pypdf; .md/.txt as-is."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def cv_to_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    else:
        text = path.read_text()
    text = "\n".join(line.rstrip() for line in text.splitlines())
    if len(text.strip()) < 200:
        raise ValueError(f"CV text too short ({len(text.strip())} chars). Is {path} a scanned PDF?")
    return text
