from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from doc_chat.ingest.loaders import SUPPORTED_EXTENSIONS

if TYPE_CHECKING:
    from doc_chat.ingest.indexer import Indexer

log = logging.getLogger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(
        self,
        indexer: "Indexer",
        debounce_seconds: float,
        event_callback: Callable[[str, str], None] | None,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self._indexer = indexer
        self._debounce = debounce_seconds
        self._event_callback = event_callback
        self._loop = loop
        self._pending: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def _schedule_flush(self) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self._debounce, self._flush)
        self._timer.daemon = True
        self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            pending = dict(self._pending)
            self._pending.clear()

        for path_str, (_, action) in pending.items():
            path = Path(path_str)
            if self._event_callback:
                self._event_callback(action, path_str)
            if action == "delete":
                asyncio.run_coroutine_threadsafe(
                    self._indexer.remove_file(path), self._loop
                )
            else:
                asyncio.run_coroutine_threadsafe(
                    self._indexer.index_file(path), self._loop
                )

    def _handle(self, event: FileSystemEvent, action: str) -> None:
        path = Path(event.src_path)
        if event.is_directory:
            return
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        with self._lock:
            self._pending[str(path)] = (time.monotonic(), action)
        self._schedule_flush()

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event, "index")

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event, "index")

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._handle(event, "delete")

    def on_moved(self, event: FileSystemEvent) -> None:
        old = Path(event.src_path)
        new = Path(event.dest_path)
        if not event.is_directory:
            if old.suffix.lower() in SUPPORTED_EXTENSIONS:
                with self._lock:
                    self._pending[str(old)] = (time.monotonic(), "delete")
            if new.suffix.lower() in SUPPORTED_EXTENSIONS:
                with self._lock:
                    self._pending[str(new)] = (time.monotonic(), "index")
            self._schedule_flush()


class DocWatcher:
    def __init__(
        self,
        path: Path,
        indexer: "Indexer",
        debounce_seconds: float = 2.0,
        event_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        self._path = path
        self._indexer = indexer
        self._debounce = debounce_seconds
        self._event_callback = event_callback
        self._observer: Observer | None = None

    def start(self) -> None:
        loop = asyncio.get_event_loop()
        handler = _Handler(
            self._indexer,
            self._debounce,
            self._event_callback,
            loop,
        )
        self._observer = Observer()
        self._observer.schedule(handler, str(self._path), recursive=True)
        self._observer.start()
        log.info("Watching %s for changes", self._path)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        log.info("Stopped watching")
