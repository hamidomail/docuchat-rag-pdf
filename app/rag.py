"""Retrieval-augmented answering: retrieve -> build grounded prompt -> stream."""
from __future__ import annotations

import re
from collections.abc import Iterator

import httpx

from .config import Settings
from .llm import LLMError, stream_chat
from .store import DocumentStore, Hit, tokenize

SYSTEM_PROMPT = """You are a precise assistant that answers questions about the user's documents.

Rules:
- Use ONLY the numbered excerpts provided in the latest message. Do not use outside knowledge.
- Cite every factual sentence with the excerpt number(s) in square brackets, e.g. [2] or [1][3].
- If the excerpts do not contain the answer, say so plainly and suggest what to ask instead.
- Answer in the same language as the question. Be concise; use short lists for steps or options.
"""

NOT_FOUND = "I couldn't find anything about that in the indexed documents. Try rephrasing, or upload the document that covers it."


def retrieval_query(question: str, history: list[dict]) -> str:
    """Short follow-ups ("and for part-time staff?") borrow the previous question."""
    if len(tokenize(question)) < 6:
        previous = [m["content"] for m in history if m.get("role") == "user"]
        if previous:
            return f"{previous[-1]} {question}"
    return question


def build_context(hits: list[Hit]) -> str:
    blocks = [
        f"[{n}] {h.chunk.doc_name}, page {h.chunk.page}\n{h.chunk.text}"
        for n, h in enumerate(hits, start=1)
    ]
    return "\n\n".join(blocks)


def build_messages(question: str, history: list[dict], hits: list[Hit]) -> list[dict]:
    turns = [m for m in history if m.get("role") in ("user", "assistant") and m.get("content")][-6:]
    if turns and turns[0]["role"] == "assistant":
        turns = turns[1:]  # conversations must start with a user turn
    prompt = f"Excerpts:\n\n{build_context(hits)}\n\nQuestion: {question}"
    return [*turns, {"role": "user", "content": prompt}]


def _segments(text: str, query: set[str], idf: dict[str, float], window: int = 26) -> list[str]:
    """Sentences; long run-on segments (tables flattened by PDF extraction) are
    cut to a window centred on the rarest query term they contain."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        words = sentence.split()
        if len(words) <= window + 8:
            out.append(sentence.strip())
            continue
        positions = [(idf.get(t, 0), i) for i, w in enumerate(words) for t in tokenize(w) if t in query]
        if not positions:
            continue
        _, pos = max(positions)
        start = max(0, pos - 3)
        piece = " ".join(words[start:start + window])
        out.append(("…" if start else "") + piece + ("…" if start + window < len(words) else ""))
    return out


def extractive_answer(question: str, hits: list[Hit], idf: dict[str, float] | None = None,
                      max_sentences: int = 3) -> str:
    """No-LLM fallback: pick the sentences whose rare words best match the question."""
    idf = idf or {}
    q = set(tokenize(question))
    scored = []
    for n, hit in enumerate(hits[:3], start=1):
        for sentence in _segments(hit.chunk.text, q, idf):
            words = tokenize(sentence)
            if len(words) < 4:
                continue
            weight = sum(idf.get(t, 1.0) for t in q.intersection(words))
            if weight:
                scored.append((weight / (len(words) ** 0.3), n, sentence))
    scored.sort(reverse=True)
    picked, seen = [], set()
    best = scored[0][0] if scored else 0
    for score, n, sentence in scored:
        if score < 0.45 * best or len(picked) == max_sentences:
            break
        if sentence not in seen:
            picked.append(f"- {sentence} [{n}]")
            seen.add(sentence)
    if not picked:
        picked = [f"- {hits[0].chunk.text[:300].strip()}… [1]"]
    return ("_Demo mode: no LLM is configured, so these are the most relevant passages "
            "rather than a written answer._\n\n" + "\n".join(picked))


def answer(store: DocumentStore, settings: Settings, question: str,
           history: list[dict] | None = None, doc_ids: list[str] | None = None) -> Iterator[dict]:
    history = history or []
    hits = store.search(retrieval_query(question, history), settings.top_k, doc_ids)
    yield {
        "type": "sources",
        "sources": [
            {"n": n, "doc_id": h.chunk.doc_id, "doc_name": h.chunk.doc_name,
             "page": h.chunk.page, "text": h.chunk.text, "score": h.score}
            for n, h in enumerate(hits, start=1)
        ],
    }
    if not hits:
        yield {"type": "token", "text": NOT_FOUND}
    elif settings.llm_provider == "none":
        for word in re.findall(r"\S+\s*", extractive_answer(question, hits, store.idf)):
            yield {"type": "token", "text": word}
    else:
        try:
            for token in stream_chat(settings, SYSTEM_PROMPT, build_messages(question, history, hits)):
                yield {"type": "token", "text": token}
        except (LLMError, httpx.HTTPError) as exc:
            yield {"type": "error", "message": str(exc)}
    yield {"type": "done"}
