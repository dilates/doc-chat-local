from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


VERSION = "1.0.0"
VERSION_TEXT = (
    f"doc-chat-local v{VERSION}\n"
    "Chat with your documents using local AI — no cloud required\n"
    "https://github.com/dilates"
)


def _make_components(args):
    from doc_chat.config import load_config, save_state
    from doc_chat.store.vectordb import VectorStore
    from doc_chat.llm.ollama_client import OllamaClient

    data_dir = Path(args.data_dir).expanduser() if getattr(args, "data_dir", None) else None
    ollama_host = getattr(args, "ollama_host", None)
    config_path = Path(args.config) if getattr(args, "config", None) else None

    config = load_config(config_path=config_path, data_dir=data_dir, ollama_host=ollama_host)
    config.data_dir.mkdir(parents=True, exist_ok=True)

    vectordb = VectorStore(config.chroma_dir)
    ollama = OllamaClient(host=config.ollama_host)
    return config, vectordb, ollama


async def _cmd_index(args) -> int:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from doc_chat.ingest.indexer import Indexer
    from doc_chat.config import save_state

    console = Console()
    config, vectordb, ollama = _make_components(args)

    connected = await ollama.check_connection()
    if not connected:
        console.print(
            "[bold red]Error:[/] Cannot connect to Ollama at "
            f"{config.ollama_host}\nTry: ollama serve"
        )
        return 1

    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        console.print(f"[bold red]Error:[/] Path does not exist: {path}")
        return 1

    config.last_indexed_path = str(path)
    save_state(config)

    indexer = Indexer(vectordb, ollama, config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Indexing...", total=100)

        def on_progress(current: int, total: int, current_file: str) -> None:
            pct = int((current / total * 100) if total else 100)
            name = Path(current_file).name if current_file else ""
            progress.update(task, completed=pct, description=f"Indexing {name}")

        result = await indexer.index_directory(path, progress_callback=on_progress)

    console.print(f"\n[bold green]Done![/] Indexed [bold]{path}[/]")
    console.print(
        f"  Files processed : {result.files_processed}\n"
        f"  Files unchanged : {result.files_unchanged}\n"
        f"  Files skipped   : {result.files_skipped}\n"
        f"  Chunks created  : {result.chunks_created}\n"
        f"  Time            : {result.duration_seconds:.1f}s"
    )
    if result.errors:
        console.print("\n[yellow]Warnings:[/]")
        for e in result.errors[:10]:
            console.print(f"  • {e}")

    if getattr(args, "watch", False):
        from doc_chat.watcher import DocWatcher
        console.print(f"\n[dim]Watching {path} for changes (Ctrl+C to stop)...[/]")
        watcher = DocWatcher(
            path, indexer,
            debounce_seconds=config.watch.debounce_seconds,
            event_callback=lambda action, p: console.print(f"[dim]{action}: {Path(p).name}[/]"),
        )
        watcher.start()
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            watcher.stop()

    await ollama.close()
    return 0


async def _cmd_add(args) -> int:
    args.watch = False
    return await _cmd_index(args)


async def _cmd_remove(args) -> int:
    from rich.console import Console
    from doc_chat.ingest.indexer import Indexer

    console = Console()
    config, vectordb, ollama = _make_components(args)
    path = Path(args.path).expanduser().resolve()
    indexer = Indexer(vectordb, ollama, config)
    await indexer.remove_file(path)
    console.print(f"[green]Removed[/] {path} from index.")
    await ollama.close()
    return 0


async def _cmd_query(args) -> int:
    from rich.console import Console
    from rich.markdown import Markdown
    from doc_chat.llm.rag import RAGPipeline

    console = Console()
    config, vectordb, ollama = _make_components(args)

    connected = await ollama.check_connection()
    if not connected:
        console.print(f"[bold red]Error:[/] Cannot connect to Ollama at {config.ollama_host}")
        await ollama.close()
        return 1

    stats = vectordb.get_stats()
    if stats.total_chunks == 0:
        console.print(
            "[yellow]No documents indexed yet.[/]\n"
            "Run: doc-chat index ~/Documents/notes"
        )
        await ollama.close()
        return 1

    pipeline = RAGPipeline(vectordb, ollama, config)
    n_results = getattr(args, "n", config.n_results)

    async for event in await pipeline.query(args.question, n_results=n_results):
        if event.type == "retrieval":
            if event.retrieved_chunks:
                sources = {rc.chunk.source_path for rc in event.retrieved_chunks}
                console.print(f"[dim]Sources: {', '.join(Path(s).name for s in sources)}[/]\n")
        elif event.type == "token":
            print(event.token, end="", flush=True)
        elif event.type == "error":
            console.print(f"\n[red]Error:[/] {event.error}")
            await ollama.close()
            return 1
        elif event.type == "done":
            print()

    await ollama.close()
    return 0


async def _cmd_status(args) -> int:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    config, vectordb, ollama = _make_components(args)
    stats = vectordb.get_stats()

    connected = await ollama.check_connection()
    conn_str = "[green]● connected[/]" if connected else "[red]● disconnected[/]"

    table = Table(title="doc-chat-local status", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Ollama", conn_str)
    table.add_row("Documents", str(stats.total_documents))
    table.add_row("Chunks", str(stats.total_chunks))
    table.add_row("Storage", f"{stats.storage_size_mb:.1f} MB")
    if stats.last_indexed:
        table.add_row("Last indexed", stats.last_indexed.strftime("%Y-%m-%d %H:%M"))
    table.add_row("Embed model", config.embed_model)
    table.add_row("Chat model", config.chat_model or "(auto)")
    table.add_row("Data dir", str(config.data_dir))

    if stats.by_type:
        table.add_row("By type", ", ".join(f"{k}:{v}" for k, v in stats.by_type.items()))

    console.print(table)
    await ollama.close()
    return 0


async def _cmd_clear(args) -> int:
    from rich.console import Console
    import shutil

    console = Console()
    config, vectordb, ollama = _make_components(args)

    confirm = input("This will wipe the entire index. Type 'yes' to confirm: ")
    if confirm.strip().lower() != "yes":
        console.print("Aborted.")
        await ollama.close()
        return 0

    chroma_dir = config.chroma_dir
    if chroma_dir.exists():
        shutil.rmtree(chroma_dir)
    console.print("[green]Index cleared.[/]")
    await ollama.close()
    return 0


async def _cmd_models(args) -> int:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    config, vectordb, ollama = _make_components(args)

    connected = await ollama.check_connection()
    if not connected:
        console.print(f"[red]Cannot connect to Ollama at {config.ollama_host}[/]")
        await ollama.close()
        return 1

    models = await ollama.list_models()
    table = Table(title="Available Ollama models")
    table.add_column("Model")
    table.add_column("Role")
    for m in models:
        roles: list[str] = []
        if m == config.embed_model:
            roles.append("embed (configured)")
        if m == config.chat_model:
            roles.append("chat (configured)")
        table.add_row(m, ", ".join(roles) if roles else "")

    console.print(table)
    console.print(f"\nConfigured embed: [bold]{config.embed_model}[/]")
    console.print(f"Configured chat : [bold]{config.chat_model or '(auto — first available)'}[/]")
    await ollama.close()
    return 0


async def _cmd_tui(args) -> int:
    from doc_chat.tui.app import DocChatApp
    config, vectordb, ollama = _make_components(args)
    app = DocChatApp(config=config, vectordb=vectordb, ollama=ollama)
    await app.run_async()
    return 0


async def _cmd_serve(args) -> int:
    import uvicorn
    from doc_chat.web.server import create_app
    config, vectordb, ollama = _make_components(args)
    app = create_app(config=config, vectordb=vectordb, ollama=ollama)
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8420)
    from rich.console import Console
    Console().print(
        f"[green]Starting web UI at[/] http://{host}:{port}\n"
        "Open in your browser to start chatting."
    )
    config_uvi = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config_uvi)
    await server.serve()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc-chat",
        description="Chat with your documents using local AI",
    )
    parser.add_argument("--version", action="version", version=VERSION_TEXT)
    parser.add_argument("--data-dir", metavar="PATH", default=None)
    parser.add_argument("--config", metavar="PATH", default=None)
    parser.add_argument("--ollama-host", metavar="URL", default=None)

    sub = parser.add_subparsers(dest="command")

    p_index = sub.add_parser("index", help="Index a directory")
    p_index.add_argument("path")
    p_index.add_argument("--watch", action="store_true")

    p_add = sub.add_parser("add", help="Index a file or directory (one-shot)")
    p_add.add_argument("path")

    p_remove = sub.add_parser("remove", help="Remove a file from the index")
    p_remove.add_argument("path")

    p_query = sub.add_parser("query", help="One-shot query")
    p_query.add_argument("question")
    p_query.add_argument("--n", type=int, default=None, metavar="N")

    sub.add_parser("tui", help="Launch TUI")

    p_serve = sub.add_parser("serve", help="Launch web UI")
    p_serve.add_argument("--port", type=int, default=8420)
    p_serve.add_argument("--host", default="127.0.0.1")

    sub.add_parser("status", help="Show index stats")
    sub.add_parser("clear", help="Wipe the index")
    sub.add_parser("models", help="List Ollama models")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    handlers = {
        "index": _cmd_index,
        "add": _cmd_add,
        "remove": _cmd_remove,
        "query": _cmd_query,
        "tui": _cmd_tui,
        "serve": _cmd_serve,
        "status": _cmd_status,
        "clear": _cmd_clear,
        "models": _cmd_models,
    }

    if args.command is None:
        if sys.stdout.isatty():
            args.command = "tui"
        else:
            parser.print_help()
            sys.exit(0)

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        code = asyncio.run(handler(args))
        sys.exit(code)
    except KeyboardInterrupt:
        sys.exit(0)
