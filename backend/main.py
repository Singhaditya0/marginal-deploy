"""
main.py
-------
FastAPI app tying together document_processor, rag_engine, and llm_service.
Run with:  uvicorn main:app --reload --port 8000
"""

import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from document_processor import process_document, DocumentProcessorError
from rag_engine import store
from llm_service import summarize, answer_question, LLMServiceError

app = FastAPI(title="Intelligent Document Summarizer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# In-memory cache of full document text, keyed by doc_id, so /summarize
# doesn't need to re-fetch anything and the source panel can show full text.
_full_text_cache: dict[str, str] = {}


class AskRequest(BaseModel):
    question: str
    top_k: int = 5


class SummarizeRequest(BaseModel):
    style: str = "concise"


class UrlUploadRequest(BaseModel):
    url: str


class TextUploadRequest(BaseModel):
    text: str
    name: str = "Pasted text"


@app.post("/api/upload/file")
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename or "document"
    suffix = Path(filename).suffix.lower().lstrip(".")

    type_map = {"pdf": "pdf", "docx": "docx", "doc": "docx", "txt": "txt", "md": "txt"}
    source_type = type_map.get(suffix)
    if source_type is None:
        raise HTTPException(400, f"Unsupported file type: .{suffix}. Use PDF, DOCX, or TXT.")

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(400, "Uploaded file is empty.")

    try:
        chunks, full_text = process_document(source_type, raw_bytes)
    except DocumentProcessorError as exc:
        raise HTTPException(422, str(exc)) from exc

    doc_id = str(uuid.uuid4())
    store.add_document(
        doc_id,
        chunks,
        metadata={"name": filename, "source_type": source_type, "num_chunks": len(chunks)},
    )
    _full_text_cache[doc_id] = full_text

    return {
        "doc_id": doc_id,
        "name": filename,
        "num_chunks": len(chunks),
        "preview": full_text[:400],
    }


@app.post("/api/upload/url")
async def upload_url(payload: UrlUploadRequest):
    try:
        chunks, full_text = process_document("url", payload.url)
    except DocumentProcessorError as exc:
        raise HTTPException(422, str(exc)) from exc

    doc_id = str(uuid.uuid4())
    display_name = payload.url
    store.add_document(
        doc_id,
        chunks,
        metadata={"name": display_name, "source_type": "url", "num_chunks": len(chunks)},
    )
    _full_text_cache[doc_id] = full_text

    return {
        "doc_id": doc_id,
        "name": display_name,
        "num_chunks": len(chunks),
        "preview": full_text[:400],
    }


@app.post("/api/upload/text")
async def upload_text(payload: TextUploadRequest):
    if not payload.text.strip():
        raise HTTPException(400, "Pasted text is empty.")

    try:
        chunks, full_text = process_document("text", payload.text)
    except DocumentProcessorError as exc:
        raise HTTPException(422, str(exc)) from exc

    doc_id = str(uuid.uuid4())
    store.add_document(
        doc_id,
        chunks,
        metadata={"name": payload.name, "source_type": "text", "num_chunks": len(chunks)},
    )
    _full_text_cache[doc_id] = full_text

    return {
        "doc_id": doc_id,
        "name": payload.name,
        "num_chunks": len(chunks),
        "preview": full_text[:400],
    }


@app.get("/api/documents")
async def list_documents():
    return {"documents": store.list_documents()}


@app.get("/api/documents/{doc_id}/text")
async def get_document_text(doc_id: str):
    if doc_id not in _full_text_cache:
        raise HTTPException(404, "Document not found.")
    return {"doc_id": doc_id, "text": _full_text_cache[doc_id]}


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    store.delete_document(doc_id)
    _full_text_cache.pop(doc_id, None)
    return {"status": "deleted"}


@app.post("/api/documents/{doc_id}/summarize")
async def summarize_document(doc_id: str, payload: SummarizeRequest):
    if doc_id not in _full_text_cache:
        raise HTTPException(404, "Document not found.")
    try:
        result = summarize(_full_text_cache[doc_id], style=payload.style)
    except LLMServiceError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"doc_id": doc_id, "summary": result}


@app.post("/api/documents/{doc_id}/ask")
async def ask_document(doc_id: str, payload: AskRequest):
    try:
        index = store.get_index(doc_id)
    except KeyError as exc:
        raise HTTPException(404, "Document not found.") from exc

    retrieved = index.search(payload.question, k=payload.top_k)
    try:
        answer = answer_question(payload.question, retrieved)
    except LLMServiceError as exc:
        raise HTTPException(503, str(exc)) from exc

    sources = [
        {"rank": i + 1, "text": chunk, "score": round(score, 3), "chunk_index": idx}
        for i, (chunk, score, idx) in enumerate(retrieved)
    ]

    return {"doc_id": doc_id, "answer": answer, "sources": sources}


# Serve the frontend as static files
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(FRONTEND_DIR / "index.html"))
