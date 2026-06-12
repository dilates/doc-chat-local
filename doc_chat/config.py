from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WatchConfig:
    debounce_seconds: float = 2.0
    ignore_patterns: list[str] = field(default_factory=lambda: [
        "node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build"
    ])


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path.home() / ".local" / "share" / "doc-chat")
    ollama_host: str = "http://127.0.0.1:11434"
    embed_model: str = "nomic-embed-text"
    chat_model: str = ""
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 50
    n_results: int = 5
    conversation_history_length: int = 5
    watch: WatchConfig = field(default_factory=WatchConfig)
    last_indexed_path: str = ""

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "state.toml"


def _find_config_file(override: Path | None = None) -> Path | None:
    if override is not None:
        return override if override.exists() else None
    candidates = [
        Path.cwd() / ".doc-chat.toml",
        Path.home() / ".config" / "doc-chat" / "config.toml",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def load_config(
    config_path: Path | None = None,
    data_dir: Path | None = None,
    ollama_host: str | None = None,
) -> Config:
    cfg = Config()

    found = _find_config_file(config_path)
    if found is not None:
        with open(found, "rb") as f:
            raw = tomllib.load(f)
        section = raw.get("doc-chat", {})
        watch_section = section.pop("watch", {})

        if "data_dir" in section:
            cfg.data_dir = Path(section["data_dir"]).expanduser()
        if "ollama_host" in section:
            cfg.ollama_host = section["ollama_host"]
        if "embed_model" in section:
            cfg.embed_model = section["embed_model"]
        if "chat_model" in section:
            cfg.chat_model = section["chat_model"]
        if "chunk_size_tokens" in section:
            cfg.chunk_size_tokens = int(section["chunk_size_tokens"])
        if "chunk_overlap_tokens" in section:
            cfg.chunk_overlap_tokens = int(section["chunk_overlap_tokens"])
        if "n_results" in section:
            cfg.n_results = int(section["n_results"])
        if "conversation_history_length" in section:
            cfg.conversation_history_length = int(section["conversation_history_length"])

        if watch_section:
            if "debounce_seconds" in watch_section:
                cfg.watch.debounce_seconds = float(watch_section["debounce_seconds"])
            if "ignore_patterns" in watch_section:
                cfg.watch.ignore_patterns = list(watch_section["ignore_patterns"])

    if data_dir is not None:
        cfg.data_dir = data_dir.expanduser()
    if ollama_host is not None:
        cfg.ollama_host = ollama_host

    _load_state(cfg)
    return cfg


def _load_state(cfg: Config) -> None:
    if cfg.state_file.exists():
        try:
            with open(cfg.state_file, "rb") as f:
                state = tomllib.load(f)
            cfg.last_indexed_path = state.get("last_indexed_path", "")
        except Exception:
            pass


def save_state(cfg: Config) -> None:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    content = f'last_indexed_path = "{cfg.last_indexed_path}"\n'
    cfg.state_file.write_text(content)
