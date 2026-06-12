from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import chromadb

if TYPE_CHECKING:
    from doc_chat.ingest.chunker import Chunk

log = logging.getLogger(__name__)

COLLECTION_NAME = "documents"


@dataclass
class RetrievedChunk:
    chunk: "Chunk"
    distance: float
    similarity: float


@dataclass
class IndexStats:
    total_documents: int
    total_chunks: int
    by_type: dict[str, int]
    last_indexed: datetime | None
    storage_size_mb: float


class VectorStore:
    def __init__(self, persist_dir: Path) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        self._persist_dir = persist_dir

    def upsert_chunks(self, chunks: list["Chunk"], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        ids = [c.id for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = []
        for c in chunks:
            meta: dict[str, str | int | float | bool] = {
                "source_path": c.source_path,
                "doc_type": c.doc_type,
            }
            for k, v in c.metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    meta[k] = v
                elif isinstance(v, dict):
                    pass
                else:
                    meta[k] = str(v)
            metadatas.append(meta)

        self._collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[RetrievedChunk]:
        from doc_chat.ingest.chunker import Chunk

        total = self._collection.count()
        if total == 0:
            return []

        n_results = min(n_results, total)
        kwargs: dict = dict(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)
        retrieved: list[RetrievedChunk] = []

        ids = results["ids"][0]
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        for cid, text, meta, dist in zip(ids, docs, metas, distances):
            chunk = Chunk(
                id=cid,
                text=text,
                source_path=meta.get("source_path", ""),
                doc_type=meta.get("doc_type", ""),
                metadata={k: v for k, v in meta.items() if k not in ("source_path", "doc_type")},
            )
            similarity = max(0.0, 1.0 - dist)
            retrieved.append(RetrievedChunk(chunk=chunk, distance=dist, similarity=similarity))

        return retrieved

    def delete_by_source(self, source_path: str) -> None:
        try:
            self._collection.delete(where={"source_path": source_path})
        except Exception as exc:
            log.warning("Error deleting chunks for %s: %s", source_path, exc)

    def get_indexed_sources(self) -> dict[str, str]:
        try:
            results = self._collection.get(include=["metadatas"])
        except Exception:
            return {}
        sources: dict[str, str] = {}
        for meta in results.get("metadatas") or []:
            sp = meta.get("source_path", "")
            ch = meta.get("content_hash", "")
            if sp and ch:
                sources[sp] = ch
            elif sp and sp not in sources:
                sources[sp] = ""
        return sources

    def store_content_hash(self, source_path: str, content_hash: str) -> None:
        existing = self._collection.get(
            where={"source_path": source_path},
            include=["metadatas"],
            limit=1,
        )
        ids = existing.get("ids", [])
        if ids:
            self._collection.update(
                ids=[ids[0]],
                metadatas=[{**existing["metadatas"][0], "content_hash": content_hash}],
            )

    def get_content_hash(self, source_path: str) -> str | None:
        try:
            results = self._collection.get(
                where={"source_path": source_path},
                include=["metadatas"],
                limit=1,
            )
        except Exception:
            return None
        metas = results.get("metadatas") or []
        if metas:
            return metas[0].get("content_hash")
        return None

    def upsert_source_hash(self, source_path: str, content_hash: str, doc_type: str) -> None:
        """Store the content hash for a source file as a special metadata-only entry."""
        hash_id = f"__hash__{source_path}"
        self._collection.upsert(
            ids=[hash_id],
            documents=[""],
            embeddings=[[0.0]],
            metadatas=[{
                "source_path": source_path,
                "content_hash": content_hash,
                "doc_type": doc_type,
                "_hash_entry": True,
            }],
        )

    def get_source_hash(self, source_path: str) -> str | None:
        hash_id = f"__hash__{source_path}"
        try:
            result = self._collection.get(ids=[hash_id], include=["metadatas"])
            metas = result.get("metadatas") or []
            if metas:
                return metas[0].get("content_hash")
        except Exception:
            pass
        return None

    def delete_source_hash(self, source_path: str) -> None:
        hash_id = f"__hash__{source_path}"
        try:
            self._collection.delete(ids=[hash_id])
        except Exception:
            pass

    def get_stats(self) -> IndexStats:
        total_chunks = self._collection.count()

        try:
            all_meta = self._collection.get(include=["metadatas"])
            metas = all_meta.get("metadatas") or []
        except Exception:
            metas = []

        sources: set[str] = set()
        by_type: dict[str, int] = {}
        last_indexed: datetime | None = None

        for meta in metas:
            if meta.get("_hash_entry"):
                continue
            sp = meta.get("source_path", "")
            if sp:
                sources.add(sp)
            dt = meta.get("doc_type", "unknown")
            by_type[dt] = by_type.get(dt, 0) + 1
            ts = meta.get("indexed_at")
            if ts:
                try:
                    dt_obj = datetime.fromisoformat(ts)
                    if last_indexed is None or dt_obj > last_indexed:
                        last_indexed = dt_obj
                except ValueError:
                    pass

        storage_mb = 0.0
        try:
            total_size = sum(
                f.stat().st_size for f in self._persist_dir.rglob("*") if f.is_file()
            )
            storage_mb = total_size / (1024 * 1024)
        except Exception:
            pass

        return IndexStats(
            total_documents=len(sources),
            total_chunks=total_chunks,
            by_type=by_type,
            last_indexed=last_indexed,
            storage_size_mb=round(storage_mb, 2),
        )
