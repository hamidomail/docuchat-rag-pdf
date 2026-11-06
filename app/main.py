"""FastAPI server: document management, streaming chat (Server-Sent Events), web UI.

Run with:  uvicorn app.main:create_app --factory --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .rag import answer
from .store import DocumentStore, DuplicateDocument, make_embedder

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = []
    doc_ids: list[str] | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = DocumentStore(settings, make_embedder(settings))
    app = FastAPI(title="DocuChat — RAG over PDFs", version="1.0.0")
    app.state.settings, app.state.store = settings, store

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "llm_provider": settings.llm_provider,
            "model": settings.model_label,
            "retrieval": "hybrid (BM25 + embeddings)" if store.embedder else "BM25 keyword",
            "documents": len(store.documents),
            "chunks": len(store.chunks),
        }

    @app.get("/api/documents")
    def list_documents():
        return [{k: v for k, v in d.items() if k != "sha256"} for d in store.list_documents()]

    @app.post("/api/documents", status_code=201)
    async def upload_document(file: UploadFile = File(...)):
        name = Path(file.filename or "document.pdf").name
        if not name.lower().endswith(".pdf"):
            raise HTTPException(415, "Only PDF files are supported.")
        data = await file.read()
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
        if not data.startswith(b"%PDF"):
            raise HTTPException(415, "This file is not a valid PDF.")
        try:
            doc = store.add_pdf(name, data)
        except DuplicateDocument as dup:
            raise HTTPException(409, f"{dup.doc['name']} is already in the library.") from dup
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {k: v for k, v in doc.items() if k != "sha256"}

    @app.delete("/api/documents/{doc_id}", status_code=204)
    def delete_document(doc_id: str):
        if not store.delete_document(doc_id):
            raise HTTPException(404, "Document not found.")

    @app.post("/api/search")
    def search(req: ChatRequest):
        hits = store.search(req.question, settings.top_k, req.doc_ids)
        return [{"doc_name": h.chunk.doc_name, "page": h.chunk.page, "score": h.score,
                 "text": h.chunk.text} for h in hits]

    @app.post("/api/chat")
    def chat(req: ChatRequest):
        history = [m.model_dump() for m in req.history]

        def event_stream():
            for event in answer(store, settings, req.question, history, req.doc_ids):
                yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app

