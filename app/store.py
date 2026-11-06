"""Document index: BM25 keyword search + optional dense embeddings, fused with
Reciprocal Rank Fusion (RRF). Persisted to disk as JSON + a NumPy matrix, so it
needs no external vector database for small and medium corpora.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .config import Settings
from .ingest import extract_pages, pdf_title, split_text

STOPWORDS = set(
    """a an the and or but if of to in on at by for with from as is are was were be been being
    it its this that these those i you he she we they me my your our their what which who whom
    how when where why do does did can could should would will shall may might must not no so
    than then there here about into over under also just only very any all each such
    le la les un une des du de et ou mais si à au aux en dans sur par pour avec est sont été être
    ce cet cette ces je tu il elle nous vous ils elles que qui quoi comment quand où pourquoi
    ne pas plus ou se sa son ses leur leurs""".split()
)

_TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    tokens = []
    for tok in _TOKEN.findall(text.lower()):
        if tok in STOPWORDS or len(tok) < 2:
            continue
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]  # light plural folding: "holidays" -> "holiday"
        tokens.append(tok)
    return tokens


class BM25:
    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(doc) for doc in corpus]
        self.len = np.array([len(doc) for doc in corpus], dtype=float)
        self.avgdl = float(self.len.mean()) if len(corpus) else 0.0
        df = Counter(term for doc in corpus for term in set(doc))
        n = len(corpus)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(len(self.tf))
        if not self.tf:
            return out
        for term in set(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(term)
                if f:
                    denom = f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avgdl)
                    out[i] += idf * f * (self.k1 + 1) / denom
        return out


# ---------------------------------------------------------------- embeddings
class Embedder:
    def embed(self, texts: list[str]) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError


class OpenAICompatibleEmbedder(Embedder):
    """Works with OpenAI, Azure-style gateways, Ollama (/v1), LM Studio, etc."""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url, self.api_key, self.model = base_url, api_key, model

    def embed(self, texts: list[str]) -> np.ndarray:
        import httpx

        vectors: list[list[float]] = []
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        with httpx.Client(timeout=60) as client:
            for i in range(0, len(texts), 64):
                r = client.post(f"{self.base_url}/embeddings", headers=headers,
                                json={"model": self.model, "input": texts[i:i + 64]})
                r.raise_for_status()
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                vectors.extend(d["embedding"] for d in data)
        return _normalize(np.array(vectors, dtype=np.float32))


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model: str):
        from sentence_transformers import SentenceTransformer  # optional dependency

        self.model = SentenceTransformer(model)

    def embed(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.asarray(self.model.encode(texts), dtype=np.float32))


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.clip(norms, 1e-12, None)


def make_embedder(settings: Settings) -> Embedder | None:
    if settings.embeddings_provider == "openai":
        return OpenAICompatibleEmbedder(settings.openai_base_url, settings.openai_api_key,
                                        settings.embeddings_model)
    if settings.embeddings_provider == "sentence-transformers":
        return SentenceTransformerEmbedder(settings.embeddings_model)
    return None


# --------------------------------------------------------------------- store
@dataclass
class Chunk:
    id: str
    doc_id: str
    doc_name: str
    page: int
    text: str


@dataclass
class Hit:
    chunk: Chunk
    score: float


class DuplicateDocument(Exception):
    def __init__(self, doc: dict):
        super().__init__(f"'{doc['name']}' is already indexed")
        self.doc = doc


class DocumentStore:
    RRF_K = 60

    def __init__(self, settings: Settings, embedder: Embedder | None = None):
        self.settings = settings
        self.embedder = embedder
        self.dir = Path(settings.data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.documents: dict[str, dict] = {}
        self.chunks: list[Chunk] = []
        self.vectors: np.ndarray | None = None
        self._bm25: BM25 | None = None
        self._load()

    # persistence ---------------------------------------------------------
    @property
    def _index_path(self) -> Path:
        return self.dir / "index.json"

    @property
    def _vectors_path(self) -> Path:
        return self.dir / "embeddings.npy"

    def _load(self) -> None:
        if self._index_path.exists():
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
            self.documents = raw.get("documents", {})
            self.chunks = [Chunk(**c) for c in raw.get("chunks", [])]
        if self.embedder and self._vectors_path.exists():
            vectors = np.load(self._vectors_path)
            self.vectors = vectors if len(vectors) == len(self.chunks) else None
        if self.embedder and self.chunks and self.vectors is None:
            self.vectors = self.embedder.embed([c.text for c in self.chunks])  # re-embed after a provider change
        self._rebuild_bm25()

    def _save(self) -> None:
        payload = {"documents": self.documents, "chunks": [asdict(c) for c in self.chunks]}
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._index_path)
        if self.vectors is not None:
            np.save(self._vectors_path, self.vectors)
        elif self._vectors_path.exists():
            self._vectors_path.unlink()

    def _rebuild_bm25(self) -> None:
        self._bm25 = BM25([tokenize(f"{c.doc_name} {c.text}") for c in self.chunks])

    # documents -----------------------------------------------------------
    def list_documents(self) -> list[dict]:
        return sorted(self.documents.values(), key=lambda d: d["added_at"])

    def add_pdf(self, filename: str, pdf_bytes: bytes) -> dict:
        digest = hashlib.sha256(pdf_bytes).hexdigest()
        for doc in self.documents.values():
            if doc["sha256"] == digest:
                raise DuplicateDocument(doc)

        pages = extract_pages(pdf_bytes)
        if not pages:
            raise ValueError("No extractable text found. Scanned PDFs need OCR first.")

        doc_id = uuid.uuid4().hex[:12]
        new_chunks = [
            Chunk(id=f"{doc_id}-{page.number}-{j}", doc_id=doc_id, doc_name=filename,
                  page=page.number, text=piece)
            for page in pages
            for j, piece in enumerate(split_text(page.text, self.settings.chunk_size,
                                                 self.settings.chunk_overlap))
        ]
        new_vectors = self.embedder.embed([c.text for c in new_chunks]) if self.embedder else None

        doc = {
            "id": doc_id,
            "name": filename,
            "title": pdf_title(pdf_bytes) or Path(filename).stem.replace("_", " ").replace("-", " "),
            "pages": max(p.number for p in pages),
            "chunks": len(new_chunks),
            "sha256": digest,
            "added_at": time.time(),
        }
        with self._lock:
            self.documents[doc_id] = doc
            self.chunks.extend(new_chunks)
            if new_vectors is not None:
                self.vectors = new_vectors if self.vectors is None else np.vstack([self.vectors, new_vectors])
            self._rebuild_bm25()
            self._save()
        return doc

    def delete_document(self, doc_id: str) -> bool:
        with self._lock:
            if doc_id not in self.documents:
                return False
            keep = [i for i, c in enumerate(self.chunks) if c.doc_id != doc_id]
            self.chunks = [self.chunks[i] for i in keep]
            if self.vectors is not None:
                self.vectors = self.vectors[keep] if keep else None
            del self.documents[doc_id]
            self._rebuild_bm25()
            self._save()
        return True

    # retrieval -----------------------------------------------------------
    @property
    def idf(self) -> dict[str, float]:
        return self._bm25.idf if self._bm25 else {}

    def search(self, query: str, k: int | None = None, doc_ids: list[str] | None = None) -> list[Hit]:
        k = k or self.settings.top_k
        if not self.chunks or not query.strip():
            return []
        allowed = np.array([doc_ids is None or c.doc_id in doc_ids for c in self.chunks])

        lexical = self._bm25.scores(tokenize(query)) if self._bm25 else np.zeros(len(self.chunks))
        lexical = np.where(allowed, lexical, 0.0)
        rankings = [np.argsort(-lexical)[: max(k * 4, 20)]]
        rankings[0] = np.array([i for i in rankings[0] if lexical[i] > 0], dtype=int)

        dense = None
        if self.embedder is not None and self.vectors is not None:
            q = self.embedder.embed([query])[0]
            dense = np.where(allowed, self.vectors @ q, -1.0)
            top_dense = np.argsort(-dense)[: max(k * 4, 20)]
            rankings.append(np.array([i for i in top_dense if dense[i] > 0.2], dtype=int))

        fused: dict[int, float] = {}
        for ranking in rankings:
            for rank, idx in enumerate(ranking):
                fused[int(idx)] = fused.get(int(idx), 0.0) + 1.0 / (self.RRF_K + rank + 1)

        best = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [Hit(chunk=self.chunks[i], score=round(s, 5)) for i, s in best]
