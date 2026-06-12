from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, TYPE_CHECKING

if TYPE_CHECKING:
    from doc_chat.config import Config
    from doc_chat.llm.ollama_client import OllamaClient
    from doc_chat.store.vectordb import RetrievedChunk, VectorStore

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a helpful assistant answering questions based on the user's local documents. "
    "Use the provided context to answer accurately. If the context doesn't contain enough "
    "information to answer, say so clearly rather than guessing. Always cite which source "
    "file(s) you used in your answer using the format [source: filename]."
)


@dataclass
class RAGEvent:
    type: str
    retrieved_chunks: list["RetrievedChunk"] | None = None
    token: str | None = None
    error: str | None = None


def _build_context(chunks: list["RetrievedChunk"]) -> str:
    parts: list[str] = []
    for rc in chunks:
        c = rc.chunk
        meta_parts: list[str] = []
        if "page_number" in c.metadata:
            meta_parts.append(f"page {c.metadata['page_number']}")
        if "line_start" in c.metadata:
            meta_parts.append(f"lines {c.metadata['line_start']}-{c.metadata.get('line_end', '?')}")
        if "function_or_class" in c.metadata:
            meta_parts.append(f"def {c.metadata['function_or_class']}")
        meta_str = ", ".join(meta_parts)
        header = f"--- {c.source_path}" + (f" ({meta_str})" if meta_str else "") + " ---"
        parts.append(f"{header}\n{c.text}")
    return "\n\n".join(parts)


def _build_user_message(context: str, question: str) -> str:
    return (
        f"Context from documents:\n\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer using only the context above. Cite sources."
    )


class RAGPipeline:
    def __init__(
        self,
        vectordb: "VectorStore",
        ollama: "OllamaClient",
        config: "Config",
    ) -> None:
        self._vectordb = vectordb
        self._ollama = ollama
        self._config = config
        self._history: list[dict] = []

    async def query(
        self,
        question: str,
        n_results: int | None = None,
    ) -> AsyncIterator[RAGEvent]:
        return self._query_gen(question, n_results)

    async def _query_gen(
        self,
        question: str,
        n_results: int | None,
    ) -> AsyncIterator[RAGEvent]:
        if n_results is None:
            n_results = self._config.n_results

        try:
            q_embedding = await self._ollama.embed(question, self._config.embed_model)
        except Exception as exc:
            yield RAGEvent(type="error", error=f"Embedding failed: {exc}")
            return

        try:
            chunks = self._vectordb.query(q_embedding, n_results=n_results)
        except Exception as exc:
            yield RAGEvent(type="error", error=f"Vector search failed: {exc}")
            return

        yield RAGEvent(type="retrieval", retrieved_chunks=chunks)

        context = _build_context(chunks)
        user_msg = _build_user_message(context, question)

        model = self._config.chat_model
        if not model:
            try:
                models = await self._ollama.list_models()
                model = models[0] if models else ""
            except Exception:
                pass
        if not model:
            yield RAGEvent(type="error", error="No chat model available. Run: ollama pull llama3.2")
            return

        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        history_limit = self._config.conversation_history_length
        if self._history:
            messages.extend(self._history[-history_limit * 2:])

        messages.append({"role": "user", "content": user_msg})

        full_response = ""
        try:
            async for token in self._ollama.chat_stream(messages, model):
                full_response += token
                yield RAGEvent(type="token", token=token)
        except Exception as exc:
            yield RAGEvent(type="error", error=f"Chat stream error: {exc}")
            return

        self._history.append({"role": "user", "content": question})
        self._history.append({"role": "assistant", "content": full_response})

        if len(self._history) > history_limit * 2:
            self._history = self._history[-(history_limit * 2):]

        yield RAGEvent(type="done")

    def clear_history(self) -> None:
        self._history.clear()
