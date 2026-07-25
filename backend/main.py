"""
main.py
-------
FastAPI app tying together document_processor, rag_engine, and llm_service.
Run with:  uvicorn main:app --reload --port 8000

Privacy note: documents are isolated per-browser using a session cookie
(see get_session_id below). There is no login — this just stops one
device/browser from seeing another device's uploads, since everything is
still held in a single in-memory store on the server.

Security note: this is a small student project, not a hardened production
service, but a few basic protections are included since it's on the public
internet: a per-session request rate limit, an upload size cap, an SSRF
guard on the "add by URL" feature (see document_processor.py), and a CORS
allow-list instead of a wildcard.
"""

import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from document_processor import process_document, DocumentProcessorError
from rag_engine import store
from llm_service import summarize, answer_question, LLMServiceError

app = FastAPI(title="Intelligent Document Summarizer")

# CORS: the frontend is served from the same origin as the API (FastAPI
# serves both), so cross-origin requests aren't actually needed for the
# app to work. Restricting this to known origins (rather than "*") means a
# script running on some other website can't quietly call this API using
# a visitor's session cookie in the background.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://marginal-deploy.onrender.com",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# In-memory cache of full document text, keyed by doc_id, so /summarize
# doesn't need to re-fetch anything and the source panel can show full text.
_full_text_cache: dict[str, str] = {}

# ---------- upload limits ----------
# Render's free tier has 512MB of RAM total for the whole app, so one huge
# upload could crash the instance for everyone. These caps keep any single
# request small enough to be safe.
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024   # 15 MB per uploaded file
MAX_PASTED_TEXT_CHARS = 2_000_000        # ~2 MB of pasted text

# ---------- session handling ----------
# No login system — just a random ID stored in a cookie so each browser
# only ever sees the documents *it* uploaded. New visitors get a cookie
# on their very first request; it's reused (and never overwritten) after
# that, so refreshing or reopening the tab keeps the same document shelf.
SESSION_COOKIE_NAME = "marginal_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 365  # 1 year


def get_session_id(request: Request, response: Response) -> str:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session_id,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
    return session_id


# ---------- rate limiting ----------
# A simple in-memory sliding window per session, applied to the
# expensive/abusable endpoints (uploads, summarize, ask). This isn't meant
# to stop a determined attacker — it just stops a runaway script or bug
# from burning through the free Groq quota or overloading the free Render
# instance. Resets whenever the server restarts, same as everything else
# that's in-memory here.
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 20

_rate_limit_log: dict[str, deque] = defaultdict(deque)


def enforce_rate_limit(session_id: str = Depends(get_session_id)) -> str:
    now = time.time()
    log = _rate_limit_log[session_id]
    while log and now - log[0] > RATE_LIMIT_WINDOW_SECONDS:
        log.popleft()
    if len(log) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(429, "Too many requests — please wait a moment and try again.")
    log.append(now)
    return session_id


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
async def upload_file(file: UploadFile = File(...), session_id: str = Depends(enforce_rate_limit)):
    filename = file.filename or "document"
    suffix = Path(filename).suffix.lower().lstrip(".")

    type_map = {"pdf": "pdf", "docx": "docx", "doc": "docx", "txt": "txt", "md": "txt"}
    source_type = type_map.get(suffix)
    if source_type is None:
        raise HTTPException(400, f"Unsupported file type: .{suffix}. Use PDF, DOCX, or TXT.")

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(400, "Uploaded file is empty.")
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(413, f"File is too large. The limit is {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB.")

    try:
        chunks, full_text = process_document(source_type, raw_bytes)
    except DocumentProcessorError as exc:
        raise HTTPException(422, str(exc)) from exc

    doc_id = str(uuid.uuid4())
    store.add_document(
        doc_id,
        chunks,
        metadata={"name": filename, "source_type": source_type, "num_chunks": len(chunks)},
        session_id=session_id,
    )
    _full_text_cache[doc_id] = full_text

    return {
        "doc_id": doc_id,
        "name": filename,
        "num_chunks": len(chunks),
        "preview": full_text[:400],
    }


@app.post("/api/upload/url")
async def upload_url(payload: UrlUploadRequest, session_id: str = Depends(enforce_rate_limit)):
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
        session_id=session_id,
    )
    _full_text_cache[doc_id] = full_text

    return {
        "doc_id": doc_id,
        "name": display_name,
        "num_chunks": len(chunks),
        "preview": full_text[:400],
    }


@app.post("/api/upload/text")
async def upload_text(payload: TextUploadRequest, session_id: str = Depends(enforce_rate_limit)):
    if not payload.text.strip():
        raise HTTPException(400, "Pasted text is empty.")
    if len(payload.text) > MAX_PASTED_TEXT_CHARS:
        raise HTTPException(413, "Pasted text is too long.")

    try:
        chunks, full_text = process_document("text", payload.text)
    except DocumentProcessorError as exc:
        raise HTTPException(422, str(exc)) from exc

    doc_id = str(uuid.uuid4())
    store.add_document(
        doc_id,
        chunks,
        metadata={"name": payload.name, "source_type": "text", "num_chunks": len(chunks)},
        session_id=session_id,
    )
    _full_text_cache[doc_id] = full_text

    return {
        "doc_id": doc_id,
        "name": payload.name,
        "num_chunks": len(chunks),
        "preview": full_text[:400],
    }


@app.get("/api/documents")
async def list_documents(session_id: str = Depends(get_session_id)):
    return {"documents": store.list_documents(session_id)}


@app.get("/api/documents/{doc_id}/text")
async def get_document_text(doc_id: str, session_id: str = Depends(get_session_id)):
    if not store.is_owner(doc_id, session_id) or doc_id not in _full_text_cache:
        raise HTTPException(404, "Document not found.")
    return {"doc_id": doc_id, "text": _full_text_cache[doc_id]}


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str, session_id: str = Depends(get_session_id)):
    was_owner = store.is_owner(doc_id, session_id)
    store.delete_document(doc_id, session_id)
    if was_owner:
        _full_text_cache.pop(doc_id, None)
    return {"status": "deleted"}


@app.post("/api/documents/{doc_id}/summarize")
async def summarize_document(doc_id: str, payload: SummarizeRequest, session_id: str = Depends(enforce_rate_limit)):
    if not store.is_owner(doc_id, session_id) or doc_id not in _full_text_cache:
        raise HTTPException(404, "Document not found.")
    try:
        result = summarize(_full_text_cache[doc_id], style=payload.style)
    except LLMServiceError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"doc_id": doc_id, "summary": result}


@app.post("/api/documents/{doc_id}/ask")
async def ask_document(doc_id: str, payload: AskRequest, session_id: str = Depends(enforce_rate_limit)):
    try:
        index = store.get_index(doc_id, session_id)
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


@app.get("/sw.js")
async def service_worker():
    # Served from the root (not /static/sw.js) so its default scope is "/"
    # and it can control the whole app, not just the /static/ subtree.
    return FileResponse(str(FRONTEND_DIR / "sw.js"), media_type="application/javascript")


@app.get("/robots.txt")
async def robots():
    return FileResponse(str(FRONTEND_DIR / "robots.txt"), media_type="text/plain")


@app.get("/sitemap.xml")
async def sitemap():
    return FileResponse(str(FRONTEND_DIR / "sitemap.xml"), media_type="application/xml")
