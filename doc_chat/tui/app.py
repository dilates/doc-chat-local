from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Footer, Header, Input, Label, MarkdownViewer,
    RichLog, Static, Button,
)

if TYPE_CHECKING:
    from doc_chat.config import Config
    from doc_chat.llm.ollama_client import OllamaClient
    from doc_chat.store.vectordb import VectorStore

FIRST_RUN_MSG = (
    "No documents indexed yet.\n"
    "Run [bold]doc-chat index <path>[/bold] in another terminal,\n"
    "or press [bold]Ctrl+I[/bold] to index a folder now."
)

OLLAMA_DOWN_MSG = (
    "⚠ Ollama not running — start it with: [bold]ollama serve[/bold]"
)


class MessageBubble(Static):
    """Single chat message."""

    def __init__(self, role: str, content: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.role = role
        self._content = content
        self.add_class(f"bubble-{role}")

    def compose(self) -> ComposeResult:
        label = "You" if self.role == "user" else "Assistant"
        yield Label(label, classes="bubble-label")
        yield Static(self._content, classes="bubble-text", markup=False)

    def append_token(self, token: str) -> None:
        text_widget = self.query_one(".bubble-text", Static)
        self._content += token
        text_widget.update(self._content)


class SourcesPanel(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Sources / Status", classes="panel-title")
        yield Static("", id="stats-text")
        yield Label("Last query sources:", classes="sources-label")
        yield Static("(none)", id="sources-list")
        yield Label("Models:", classes="sources-label")
        yield Static("", id="models-text")
        yield Static("", id="ollama-status")

    def update_stats(self, stats) -> None:
        self.query_one("#stats-text", Static).update(
            f"Indexed: {stats.total_documents} docs\n"
            f"        {stats.total_chunks} chunks"
        )

    def update_sources(self, sources: list[str]) -> None:
        if sources:
            text = "\n".join(f"• {Path(s).name}" for s in sources)
        else:
            text = "(none)"
        self.query_one("#sources-list", Static).update(text)

    def update_models(self, embed: str, chat: str) -> None:
        self.query_one("#models-text", Static).update(
            f"Model: {chat or '(auto)'}\nEmbed: {embed}"
        )

    def update_ollama(self, connected: bool) -> None:
        dot = "[green]●[/green]" if connected else "[red]●[/red]"
        status = "connected" if connected else "disconnected"
        self.query_one("#ollama-status", Static).update(f"Ollama: {dot} {status}")


class PathModal(Container):
    def compose(self) -> ComposeResult:
        yield Label("Enter folder path to index:", classes="modal-label")
        yield Input(placeholder="~/Documents/notes", id="path-input")
        yield Horizontal(
            Button("Index", id="index-btn", variant="primary"),
            Button("Cancel", id="cancel-btn"),
            classes="modal-buttons",
        )

    @on(Button.Pressed, "#index-btn")
    def on_index(self) -> None:
        val = self.query_one("#path-input", Input).value.strip()
        self.post_message(self.IndexRequested(val))

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel(self) -> None:
        self.post_message(self.Cancelled())

    class IndexRequested(App.message_class if hasattr(App, "message_class") else object):
        pass

    class Cancelled(App.message_class if hasattr(App, "message_class") else object):
        pass


class DocChatApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #main-content {
        layout: horizontal;
        height: 1fr;
    }
    #chat-panel {
        width: 70%;
        height: 100%;
        border: solid $primary;
        padding: 0 1;
    }
    #chat-log {
        height: 1fr;
        overflow-y: auto;
    }
    #input-row {
        height: auto;
        padding: 1 0 0 0;
    }
    #question-input {
        width: 1fr;
    }
    #sources-panel {
        width: 30%;
        height: 100%;
        border: solid $primary-darken-1;
        padding: 0 1;
    }
    .panel-title {
        text-style: bold;
        color: $primary;
        padding: 0 0 1 0;
    }
    .bubble-user {
        background: $primary-darken-3;
        margin: 0 0 1 0;
        padding: 0 1;
    }
    .bubble-assistant {
        background: $surface-darken-1;
        margin: 0 0 1 0;
        padding: 0 1;
    }
    .bubble-system {
        background: $error-darken-3;
        margin: 0 0 1 0;
        padding: 0 1;
    }
    .bubble-label {
        text-style: bold;
        color: $text-muted;
    }
    .bubble-text {
        color: $text;
    }
    .sources-label {
        color: $text-muted;
        margin-top: 1;
    }
    #banner {
        background: $warning-darken-2;
        color: $text;
        padding: 0 1;
        height: auto;
    }
    #path-modal {
        background: $surface;
        border: solid $primary;
        padding: 1 2;
        width: 60;
        height: auto;
        align: center middle;
        layer: dialog;
    }
    .modal-buttons {
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+r", "reindex", "Reindex"),
        Binding("ctrl+l", "clear_chat", "Clear chat"),
        Binding("ctrl+i", "index_folder", "Index folder"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    ollama_connected: reactive[bool] = reactive(True)
    is_streaming: reactive[bool] = reactive(False)

    def __init__(
        self,
        config: "Config",
        vectordb: "VectorStore",
        ollama: "OllamaClient",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._config = config
        self._vectordb = vectordb
        self._ollama = ollama
        self._rag = None
        self._current_bubble: MessageBubble | None = None
        self._modal_visible = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="banner")
        yield Horizontal(
            Vertical(
                RichLog(id="chat-log", highlight=True, markup=True),
                Horizontal(
                    Input(
                        placeholder="Ask a question...",
                        id="question-input",
                    ),
                    id="input-row",
                ),
                id="chat-panel",
            ),
            SourcesPanel(id="sources-panel"),
            id="main-content",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._check_status()
        self.query_one("#question-input", Input).focus()

    @work(exclusive=True)
    async def _check_status(self) -> None:
        connected = await self._ollama.check_connection()
        self.ollama_connected = connected

        banner = self.query_one("#banner", Static)
        if not connected:
            banner.update(OLLAMA_DOWN_MSG)
            banner.display = True
            self.query_one("#question-input", Input).disabled = True
        else:
            banner.display = False

        try:
            stats = self._vectordb.get_stats()
            sources_panel = self.query_one("#sources-panel", SourcesPanel)
            sources_panel.update_stats(stats)

            if stats.total_chunks == 0 and connected:
                log = self.query_one("#chat-log", RichLog)
                log.write(FIRST_RUN_MSG)

            chat_model = self._config.chat_model
            if not chat_model and connected:
                try:
                    models = await self._ollama.list_models()
                    chat_model = models[0] if models else ""
                except Exception:
                    pass
            sources_panel.update_models(self._config.embed_model, chat_model)
            sources_panel.update_ollama(connected)
        except Exception as exc:
            self.query_one("#chat-log", RichLog).write(f"[red]Status error: {exc}[/red]")

    @on(Input.Submitted, "#question-input")
    def on_submit(self, event: Input.Submitted) -> None:
        question = event.value.strip()
        if not question or self.is_streaming:
            return
        event.input.value = ""
        self._ask(question)

    @work(exclusive=False)
    async def _ask(self, question: str) -> None:
        from doc_chat.llm.rag import RAGPipeline

        if self._rag is None:
            self._rag = RAGPipeline(self._vectordb, self._ollama, self._config)

        log = self.query_one("#chat-log", RichLog)
        inp = self.query_one("#question-input", Input)

        self.is_streaming = True
        inp.disabled = True

        log.write(f"[bold cyan]You:[/bold cyan] {question}\n")

        response_lines: list[str] = []
        sources: list[str] = []

        try:
            async for event in await self._rag.query(question):
                if event.type == "retrieval":
                    if event.retrieved_chunks:
                        sources = list({rc.chunk.source_path for rc in event.retrieved_chunks})
                        self.query_one("#sources-panel", SourcesPanel).update_sources(sources)
                elif event.type == "token":
                    response_lines.append(event.token or "")
                elif event.type == "error":
                    log.write(f"\n[bold red]Error:[/bold red] {event.error}\n")
                    break
                elif event.type == "done":
                    pass
        except Exception as exc:
            log.write(f"\n[bold red]Error:[/bold red] {exc}\n")

        full_response = "".join(response_lines)
        if full_response:
            log.write(f"[bold green]Assistant:[/bold green] {full_response}\n")

        stats = self._vectordb.get_stats()
        self.query_one("#sources-panel", SourcesPanel).update_stats(stats)

        self.is_streaming = False
        inp.disabled = False
        inp.focus()

    def action_clear_chat(self) -> None:
        self.query_one("#chat-log", RichLog).clear()
        if self._rag:
            self._rag.clear_history()

    def action_reindex(self) -> None:
        last_path = self._config.last_indexed_path
        if not last_path:
            self.query_one("#chat-log", RichLog).write(
                "[yellow]No previous index path. Press Ctrl+I to index a folder.[/yellow]\n"
            )
            return
        self._reindex(Path(last_path))

    @work(exclusive=False)
    async def _reindex(self, path: Path) -> None:
        from doc_chat.ingest.indexer import Indexer
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[dim]Re-indexing {path}...[/dim]\n")
        indexer = Indexer(self._vectordb, self._ollama, self._config)
        result = await indexer.index_directory(path)
        log.write(
            f"[dim]Done: {result.files_processed} processed, "
            f"{result.files_unchanged} unchanged in {result.duration_seconds:.1f}s[/dim]\n"
        )
        stats = self._vectordb.get_stats()
        self.query_one("#sources-panel", SourcesPanel).update_stats(stats)

    def action_index_folder(self) -> None:
        self.query_one("#chat-log", RichLog).write(
            "[dim]Use: doc-chat index <path> in another terminal[/dim]\n"
        )

    def on_unmount(self) -> None:
        asyncio.ensure_future(self._ollama.close())
