from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from doc_chat.ingest.loaders import load_file, SUPPORTED_EXTENSIONS
from doc_chat.ingest.chunker import chunk_document

if TYPE_CHECKING:
    from doc_chat.config import Config
    from doc_chat.llm.ollama_client import OllamaClient
    from doc_chat.store.vectordb import VectorStore

log = logging.getLogger(__name__)

DEFAULT_IGNORE = {
    "node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build"
}


@dataclass
class IndexResult:
    files_processed: int = 0
    files_skipped: int = 0
    files_unchanged: int = 0
    chunks_created: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    try:
        h.update(path.read_bytes())
    except OSError:
        h.update(b"")
    return h.hexdigest()


def _load_gitignore(directory: Path):
    gi_path = directory / ".gitignore"
    if not gi_path.exists():
        return None
    try:
        import pathspec
        lines = gi_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)
    except ImportError:
        return None
    except Exception:
        return None


def _should_ignore(path: Path, base: Path, ignore_patterns: list[str], gitignore) -> bool:
    for part in path.parts:
        if part in ignore_patterns:
            return True
    if gitignore is not None:
        try:
            rel = path.relative_to(base)
            if gitignore.match_file(str(rel)):
                return True
        except ValueError:
            pass
    return False


class Indexer:
    def __init__(
        self,
        vectordb: "VectorStore",
        ollama: "OllamaClient",
        config: "Config",
    ) -> None:
        self._vectordb = vectordb
        self._ollama = ollama
        self._config = config

    async def index_directory(
        self,
        path: Path,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> IndexResult:
        start = time.monotonic()
        result = IndexResult()
        path = path.expanduser().resolve()

        ignore_patterns = list(DEFAULT_IGNORE | set(self._config.watch.ignore_patterns))
        gitignore = _load_gitignore(path)

        all_files = [
            f for f in path.rglob("*")
            if f.is_file()
            and f.suffix.lower() in SUPPORTED_EXTENSIONS
            and not _should_ignore(f, path, ignore_patterns, gitignore)
        ]

        existing_sources = self._vectordb.get_indexed_sources()
        disk_paths = {str(f) for f in all_files}

        for old_path in existing_sources:
            if old_path not in disk_paths and not old_path.startswith("__hash__"):
                log.info("Removing deleted file from index: %s", old_path)
                self._vectordb.delete_by_source(old_path)
                self._vectordb.delete_source_hash(old_path)

        total = len(all_files)
        for i, fpath in enumerate(all_files):
            if progress_callback:
                progress_callback(i, total, str(fpath))

            try:
                content_hash = _file_hash(fpath)
                stored_hash = self._vectordb.get_source_hash(str(fpath))

                if stored_hash == content_hash:
                    result.files_unchanged += 1
                    continue

                file_result = await self._index_single_file(fpath, content_hash)
                result.files_processed += file_result.files_processed
                result.files_skipped += file_result.files_skipped
                result.chunks_created += file_result.chunks_created
                result.errors.extend(file_result.errors)
            except Exception as exc:
                log.error("Error processing %s: %s", fpath, exc)
                result.errors.append(f"{fpath}: {exc}")
                result.files_skipped += 1

        if progress_callback:
            progress_callback(total, total, "")

        result.duration_seconds = time.monotonic() - start
        return result

    async def index_file(self, path: Path) -> IndexResult:
        path = path.expanduser().resolve()
        content_hash = _file_hash(path)
        return await self._index_single_file(path, content_hash)

    async def _index_single_file(self, path: Path, content_hash: str) -> IndexResult:
        result = IndexResult()

        doc = load_file(path)
        if doc is None:
            result.files_skipped += 1
            return result

        for err in doc.load_errors:
            log.warning(err)
            if not doc.content.strip():
                result.errors.append(f"Skipped {path.name}: {err}")
                result.files_skipped += 1
                return result

        if not doc.content.strip():
            result.files_skipped += 1
            return result

        chunks = chunk_document(
            doc,
            max_tokens=self._config.chunk_size_tokens,
            overlap_tokens=self._config.chunk_overlap_tokens,
        )
        if not chunks:
            result.files_skipped += 1
            return result

        for chunk in chunks:
            chunk.metadata["content_hash"] = content_hash
            chunk.metadata["indexed_at"] = datetime.now(timezone.utc).isoformat()

        try:
            texts = [c.text for c in chunks]
            embeddings = await self._ollama.embed_batch(texts, self._config.embed_model)
        except Exception as exc:
            result.errors.append(f"Embedding failed for {path.name}: {exc}")
            result.files_skipped += 1
            return result

        self._vectordb.delete_by_source(str(path))
        self._vectordb.upsert_chunks(chunks, embeddings)
        self._vectordb.upsert_source_hash(str(path), content_hash, doc.doc_type)

        result.files_processed += 1
        result.chunks_created += len(chunks)
        return result

    async def remove_file(self, path: Path) -> None:
        path = path.expanduser().resolve()
        self._vectordb.delete_by_source(str(path))
        self._vectordb.delete_source_hash(str(path))
        log.info("Removed %s from index", path)
