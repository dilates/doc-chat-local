from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncIterator, TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from doc_chat.config import Config
    from doc_chat.llm.ollama_client import OllamaClient
    from doc_chat.store.vectordb import VectorStore

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    config: "Config",
    vectordb: "VectorStore",
    ollama: "OllamaClient",
) -> FastAPI:
    app = FastAPI(title="doc-chat-local")

    app.state.config = config
    app.state.vectordb = vectordb
    app.state.ollama = ollama

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        html = (STATIC_DIR / "index.html").read_text()
        return HTMLResponse(html)

    @app.get("/api/status")
    async def status() -> dict:
        cfg: Config = app.state.config
        db: VectorStore = app.state.vectordb
        ol: OllamaClient = app.state.ollama

        connected = await ol.check_connection()
        stats = db.get_stats()

        models: list[str] = []
        chat_model = cfg.chat_model
        if connected:
            try:
                models = await ol.list_models()
                if not chat_model and models:
                    chat_model = models[0]
            except Exception:
                pass

        return {
            "connected": connected,
            "stats": {
                "total_documents": stats.total_documents,
                "total_chunks": stats.total_chunks,
                "storage_size_mb": stats.storage_size_mb,
                "by_type": stats.by_type,
                "last_indexed": stats.last_indexed.isoformat() if stats.last_indexed else None,
            },
            "models": {
                "available": models,
                "embed_model": cfg.embed_model,
                "chat_model": chat_model,
            },
        }

    @app.get("/api/models")
    async def list_models() -> dict:
        ol: OllamaClient = app.state.ollama
        try:
            models = await ol.list_models()
            return {"models": models}
        except Exception as exc:
            return {"models": [], "error": str(exc)}

    @app.post("/api/query")
    async def query_endpoint(request: Request) -> StreamingResponse:
        body = await request.json()
        question = body.get("question", "").strip()
        n_results = body.get("n_results", app.state.config.n_results)
        chat_model = body.get("chat_model")

        if not question:
            async def empty():
                yield _sse({"type": "error", "error": "Empty question"})
            return StreamingResponse(empty(), media_type="text/event-stream")

        cfg: Config = app.state.config
        if chat_model:
            cfg = _config_with_model(cfg, chat_model)

        return StreamingResponse(
            _stream_query(question, n_results, app.state.vectordb, app.state.ollama, cfg),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/index")
    async def index_endpoint(request: Request) -> StreamingResponse:
        body = await request.json()
        path_str = body.get("path", "").strip()
        if not path_str:
            async def empty():
                yield _sse({"type": "error", "error": "No path provided"})
            return StreamingResponse(empty(), media_type="text/event-stream")

        return StreamingResponse(
            _stream_index(path_str, app.state.vectordb, app.state.ollama, app.state.config),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _config_with_model(config: "Config", model: str):
    import dataclasses
    return dataclasses.replace(config, chat_model=model)


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _stream_query(
    question: str,
    n_results: int,
    vectordb: "VectorStore",
    ollama: "OllamaClient",
    config: "Config",
) -> AsyncIterator[str]:
    from doc_chat.llm.rag import RAGPipeline

    pipeline = RAGPipeline(vectordb, ollama, config)
    try:
        async for event in await pipeline.query(question, n_results=n_results):
            if event.type == "retrieval":
                chunks_data = []
                for rc in (event.retrieved_chunks or []):
                    chunks_data.append({
                        "source_path": rc.chunk.source_path,
                        "source_name": Path(rc.chunk.source_path).name,
                        "similarity": round(rc.similarity, 3),
                        "metadata": rc.chunk.metadata,
                        "text": rc.chunk.text[:500],
                    })
                yield _sse({"type": "retrieval", "chunks": chunks_data})
            elif event.type == "token":
                yield _sse({"type": "token", "token": event.token})
            elif event.type == "error":
                yield _sse({"type": "error", "error": event.error})
            elif event.type == "done":
                yield _sse({"type": "done"})
    except Exception as exc:
        yield _sse({"type": "error", "error": str(exc)})


async def _stream_index(
    path_str: str,
    vectordb: "VectorStore",
    ollama: "OllamaClient",
    config: "Config",
) -> AsyncIterator[str]:
    from doc_chat.ingest.indexer import Indexer
    from doc_chat.config import save_state

    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        yield _sse({"type": "error", "error": f"Path not found: {path}"})
        return

    indexer = Indexer(vectordb, ollama, config)
    queue: asyncio.Queue = asyncio.Queue()

    def on_progress(current: int, total: int, current_file: str) -> None:
        pct = int((current / total * 100) if total else 100)
        asyncio.get_event_loop().call_soon_threadsafe(
            queue.put_nowait,
            {"type": "progress", "current": current, "total": total, "percent": pct, "file": Path(current_file).name if current_file else ""},
        )

    async def run_index():
        try:
            result = await indexer.index_directory(path, progress_callback=on_progress)
            config.last_indexed_path = str(path)
            save_state(config)
            await queue.put({
                "type": "done",
                "files_processed": result.files_processed,
                "files_unchanged": result.files_unchanged,
                "chunks_created": result.chunks_created,
                "errors": result.errors[:5],
            })
        except Exception as exc:
            await queue.put({"type": "error", "error": str(exc)})

    task = asyncio.ensure_future(run_index())

    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=1.0)
            yield _sse(item)
            if item.get("type") in ("done", "error"):
                break
        except asyncio.TimeoutError:
            if task.done():
                break
            yield _sse({"type": "ping"})
