"""PDF text extraction and chunking.

Chunks never cross a page boundary, so every answer can cite an exact page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader


@dataclass
class Page:
    number: int  # 1-based
    text: str


def clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # re-join hyphenated words
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)           # single line breaks -> spaces
    return text.strip()


def _line_key(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def strip_running_lines(raw_pages: list[str], min_share: float = 0.6) -> list[str]:
    """Remove running headers/footers: lines (page numbers normalised) that
    repeat on most pages add noise to every chunk and hurt retrieval."""
    if len(raw_pages) < 3:
        return raw_pages
    counts: dict[str, int] = {}
    for text in raw_pages:
        for key in {_line_key(line) for line in text.splitlines() if line.strip()}:
            counts[key] = counts.get(key, 0) + 1
    repeated = {k for k, c in counts.items() if c / len(raw_pages) >= min_share and len(k) < 200}
    return ["\n".join(l for l in text.splitlines() if _line_key(l) not in repeated) for text in raw_pages]


def extract_pages(pdf_bytes: bytes) -> list[Page]:
    reader = PdfReader(BytesIO(pdf_bytes))
    raw = strip_running_lines([page.extract_text() or "" for page in reader.pages])
    pages = []
    for i, text in enumerate(raw, start=1):
        text = clean_text(text)
        if text:
            pages.append(Page(number=i, text=text))
    return pages


def pdf_title(pdf_bytes: bytes) -> str | None:
    try:
        meta = PdfReader(BytesIO(pdf_bytes)).metadata
        if not meta or not meta.title:
            return None
        return str(meta.title).strip() or None
    except Exception:  # metadata is optional; never fail an upload because of it
        return None


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def _units(text: str, chunk_size: int) -> list[str]:
    """Break text into paragraphs, then sentences, then hard slices if needed."""
    units: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= chunk_size:
            units.append(para)
            continue
        for sentence in _SENTENCE_SPLIT.split(para):
            sentence = sentence.strip()
            if len(sentence) <= chunk_size:
                units.append(sentence)
            else:
                units.extend(sentence[i:i + chunk_size] for i in range(0, len(sentence), chunk_size))
    return units


def split_text(text: str, chunk_size: int = 900, overlap: int = 150) -> list[str]:
    """Greedy packing of paragraphs/sentences into chunks of ~chunk_size chars,
    carrying `overlap` characters of context from one chunk into the next."""
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    current = ""
    for unit in _units(text, chunk_size):
        candidate = f"{current} {unit}" if current else unit
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        chunks.append(current)
        tail = current[-overlap:] if overlap else ""
        if " " in tail:
            tail = tail[tail.index(" ") + 1:]  # start the overlap on a word boundary
        current = f"{tail} {unit}" if tail and len(tail) + len(unit) < chunk_size else unit
    if current:
        chunks.append(current)
    return chunks
