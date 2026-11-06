import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.ingest import clean_text, split_text
from app.main import create_app
from app.rag import build_messages, retrieval_query
from app.store import DocumentStore, Embedder, tokenize

SAMPLES = Path(__file__).resolve().parent.parent / "sample_docs"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "LLM_PROVIDER", "EMBEDDINGS_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # ignore any developer .env
    return replace(Settings.from_env(), data_dir=tmp_path / "data")


@pytest.fixture
def store(settings):
    s = DocumentStore(settings)
    for pdf in sorted(SAMPLES.glob("*.pdf")):
        s.add_pdf(pdf.name, pdf.read_bytes())
    return s


# --------------------------------------------------------------- chunking
def test_split_respects_size_and_overlap():
    text = " ".join(f"Sentence number {i} talks about topic {i % 7}." for i in range(200))
    chunks = split_text(text, chunk_size=300, overlap=60)
    assert len(chunks) > 5
    assert all(len(c) <= 300 for c in chunks)
    # consecutive chunks share some text (the overlap)
    assert any(set(a.split()[-5:]) & set(b.split()[:12]) for a, b in zip(chunks, chunks[1:]))


def test_split_short_text_is_single_chunk():
    assert split_text("Short text.", 900, 150) == ["Short text."]
    assert split_text("   ", 900, 150) == []


def test_clean_text_rejoins_hyphenation():
    assert clean_text("informa-\ntion is\nhere") == "information is here"


def test_tokenize_folds_plurals_and_drops_stopwords():
    assert tokenize("The holidays are long") == ["holiday", "long"]


# -------------------------------------------------------------- retrieval
@pytest.mark.parametrize("question,expected_doc,expected_page", [
    ("How many vacation days do new employees get?", "northwind", 2),
    ("What does error code E4 mean?", "aurora", 3),
    ("factory reset buttons", "aurora", 3),
    ("hotel limit per night in Paris", "northwind", 3),
])
def test_search_finds_the_right_page(store, question, expected_doc, expected_page):
    top = store.search(question, k=3)[0].chunk
    assert expected_doc in top.doc_name
    assert top.page == expected_page


def test_search_without_match_returns_nothing(store):
    assert store.search("quantum chromodynamics gluon", k=3) == []


def test_duplicate_upload_is_rejected(store):
    pdf = next(SAMPLES.glob("*.pdf"))
    with pytest.raises(Exception, match="already indexed"):
        store.add_pdf("copy.pdf", pdf.read_bytes())


def test_index_persists_and_delete_works(settings, store):
    reloaded = DocumentStore(settings)
    assert len(reloaded.chunks) == len(store.chunks) > 0
    doc_id = next(iter(reloaded.documents))
    assert reloaded.delete_document(doc_id)
    assert all(c.doc_id != doc_id for c in reloaded.chunks)


def test_scope_to_one_document(store):
    aurora = next(d["id"] for d in store.documents.values() if "aurora" in d["name"])
    hits = store.search("vacation days employees", k=5, doc_ids=[aurora])
    assert all(h.chunk.doc_id == aurora for h in hits)


class KeywordEmbedder(Embedder):
    """Deterministic fake embedder: hashes tokens into a small vector space."""
    def embed(self, texts):
        m = np.zeros((len(texts), 64), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in tokenize(t):
                m[i, hash(tok) % 64] += 1
        return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)


def test_hybrid_retrieval_with_embeddings(settings):
    s = DocumentStore(settings, KeywordEmbedder())
    for pdf in sorted(SAMPLES.glob("*.pdf")):
        s.add_pdf(pdf.name, pdf.read_bytes())
    assert s.vectors.shape[0] == len(s.chunks)
    assert "aurora" in s.search("Wi-Fi pairing code app", k=3)[0].chunk.doc_name


# ------------------------------------------------------------------- prompt
def test_followup_question_borrows_previous_question():
    history = [{"role": "user", "content": "What is the hotel limit?"},
               {"role": "assistant", "content": "160 EUR [1]"}]
    assert "hotel limit" in retrieval_query("and in Paris?", history)


def test_messages_start_with_user_turn(store):
    hits = store.search("vacation", k=2)
    msgs = build_messages("vacation?", [{"role": "assistant", "content": "hi"}], hits)
    assert msgs[0]["role"] == "user" and "[1]" in msgs[-1]["content"]


# ---------------------------------------------------------------------- API
def _events(body: str):
    return [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]


def test_api_end_to_end(settings):
    client = TestClient(create_app(settings))
    assert client.get("/api/health").json()["llm_provider"] == "none"

    pdf = SAMPLES / "aurora_x2_thermostat_manual.pdf"
    r = client.post("/api/documents", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
    assert r.status_code == 201 and r.json()["pages"] == 3
    assert client.post("/api/documents", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")}).status_code == 409
    assert client.post("/api/documents", files={"file": ("x.pdf", b"not a pdf", "application/pdf")}).status_code == 415

    r = client.post("/api/chat", json={"question": "How do I do a factory reset?"})
    events = _events(r.text)
    assert events[0]["type"] == "sources" and events[0]["sources"][0]["page"] == 3
    answer = "".join(e["text"] for e in events if e["type"] == "token")
    assert "10 seconds" in answer and "[1]" in answer
    assert events[-1]["type"] == "done"

    doc_id = client.get("/api/documents").json()[0]["id"]
    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert client.get("/api/documents").json() == []


def test_running_footer_is_stripped():
    pdf = (SAMPLES / "northwind_employee_handbook.pdf").read_bytes()
    from app.ingest import extract_pages
    pages = extract_pages(pdf)
    assert not any("fictional document" in p.text for p in pages)
    assert "25 days of paid vacation" in pages[1].text
