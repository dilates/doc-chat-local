# doc-chat-local

**Chat with your own documents using local AI — no cloud, no API keys, no data leaving your machine.**

Index your notes, PDFs, code, and documentation, then ask questions in plain English. Everything runs on your hardware via [Ollama](https://ollama.ai).

> Built by [github.com/dilates](https://github.com/dilates)

---

## Screenshots

### Terminal UI (TUI)

```
┌─ doc-chat-local ─────────────────────────────────────────────────────────────┐
│ ┌─ Chat ──────────────────────────────────────┐ ┌─ Sources / Status ────────┐ │
│ │                                              │ │ Indexed: 142 docs         │ │
│ │  You: what does the config say about        │ │         1,847 chunks      │ │
│ │       retry logic?                           │ │                           │ │
│ │                                              │ │ Last query sources:       │ │
│ │  Assistant: Based on the configuration,     │ │  • config.py              │ │
│ │  retry attempts are set to 3 by default     │ │  • README.md              │ │
│ │  with exponential backoff starting at       │ │  • api/client.py          │ │
│ │  500ms. [source: src/config.py]             │ │                           │ │
│ │  ▌                                          │ │ Model: llama3.2:8b        │ │
│ │                                              │ │ Embed: nomic-embed-text   │ │
│ └──────────────────────────────────────────────┘ │ Ollama: ● connected       │ │
│ ┌──────────────────────────────────────────────┐ └───────────────────────────┘ │
│ │ > ask a question...                          │                               │
│ └──────────────────────────────────────────────┘                               │
│ [Ctrl+R] reindex  [Ctrl+L] clear chat  [Ctrl+I] index folder  [Ctrl+Q] quit   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Web UI

```
┌──────────────────────────────────────────┬──────────────────────────────┐
│  ◈ doc-chat-local          ● connected   │  Index                       │
├──────────────────────────────────────────│  Documents  142              │
│                                          │  Chunks     1,847            │
│                        ╭──────────────╮  │  Storage    48.3 MB          │
│                        │ what are the │  │  Last       2024-01-15 09:41 │
│                        │ main API     │  ├──────────────────────────────┤
│                        │ endpoints?   │  │  Models                      │
│                        ╰──────────────╯  │  Embed  nomic-embed-text     │
│                                          │  Chat   llama3.2 ▾           │
│  ╭────────────────────────────────────╮  ├──────────────────────────────┤
│  │ The API exposes three main         │  │  Index a Folder              │
│  │ endpoints: POST /api/query for     │  │  ~/Documents/notes  [Index]  │
│  │ chat, POST /api/index to ingest    │  ├──────────────────────────────┤
│  │ documents, and GET /api/status.    │  │  Last Query Sources          │
│  │ [source: api/routes.py]            │  │  • routes.py                 │
│  │                                    │  │  • README.md                 │
│  │  📎 routes.py  📎 README.md        │  │  • openapi.yaml              │
│  ╰────────────────────────────────────╯  │                              │
│                                          │                              │
│  ┌──────────────────────────────────┐    │                              │
│  │ Ask a question...            [▶] │    │                              │
│  └──────────────────────────────────┘    │  doc-chat-local              │
└──────────────────────────────────────────┴──────────────────────────────┘
```

### Indexing output

```
$ doc-chat index ~/Documents/research --watch

  ████████████████████████ 100%  Indexing paper_three.pdf...

  Done! Indexed /home/user/Documents/research
  Files processed :  47
  Files unchanged :  112
  Files skipped   :  3
  Chunks created  :  2,841
  Time            :  18.3s

  Watching /home/user/Documents/research for changes (Ctrl+C to stop)...
  index: new_notes.md
```

---

## Use Cases

**Knowledge base search**
Point doc-chat at your Obsidian vault, Notion exports, or a folder of Markdown notes. Ask questions like *"what did I write about async patterns in Python?"* and get answers with file citations.

**Codebase Q&A**
Index an entire repository. Ask *"how is authentication handled?"* or *"where are database connections initialized?"* — the model reads your actual code, not a hallucinated summary.

**Research paper assistant**
Drop a folder of PDFs and ask cross-cutting questions: *"which papers discuss transformer attention scaling laws?"* Page-level citations let you jump straight to the source.

**Internal documentation chat**
Index your team's runbooks, architecture docs, and API specs. New teammates can onboard by asking questions instead of reading hundreds of pages linearly.

**Personal second brain**
Index years of journal entries, book highlights, meeting notes. Ask *"what were my thoughts on remote work in 2022?"* — your own words, retrieved and synthesized.

**Legal or medical document review**
Keep sensitive documents completely local. No data leaves your machine — not a single character is sent to a third-party API.

---

## Installation

### Prerequisites

- **Python 3.11+**
- **[Ollama](https://ollama.ai)** running locally

**Install Ollama:**

```bash
# Linux
curl -fsSL https://ollama.ai/install.sh | sh

# macOS
brew install ollama

# Windows
# Download installer from https://ollama.ai/download
```

**Pull required models:**

```bash
ollama pull nomic-embed-text   # embedding model (required)
ollama pull llama3.2           # chat model (recommended — fast, 2GB)
```

Other good chat models to try:

| Model | Size | Notes |
|-------|------|-------|
| `llama3.2` | 2 GB | Fast, great for Q&A |
| `llama3.1:8b` | 4.7 GB | Higher quality |
| `mistral` | 4.1 GB | Strong reasoning |
| `qwen2.5:7b` | 4.7 GB | Good for code |
| `deepseek-r1:8b` | 4.9 GB | Best reasoning |

---

### Install doc-chat-local

**Option A — pip (editable):**
```bash
git clone https://github.com/dilates/doc-chat-local
cd doc-chat-local
pip install -e .
```

**Option B — with uv (faster):**
```bash
git clone https://github.com/dilates/doc-chat-local
cd doc-chat-local
uv venv && uv pip install -e .
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
```

**Option C — virtual environment (recommended for isolation):**
```bash
git clone https://github.com/dilates/doc-chat-local
cd doc-chat-local
python -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows
pip install -e .
```

Verify:
```bash
doc-chat --version
# doc-chat-local v1.0.0
# Chat with your documents using local AI — no cloud required
# https://github.com/dilates
```

---

### First run

```bash
# 1. Make sure Ollama is running
ollama serve &           # or: systemctl start ollama

# 2. Index a folder
doc-chat index ~/Documents/notes

# 3. Chat in the terminal
doc-chat tui

# or in the browser
doc-chat serve           # opens http://localhost:8420
```

---

## Commands

| Command | Description |
|---------|-------------|
| `doc-chat index PATH` | Index a directory (incremental — skips unchanged files) |
| `doc-chat index PATH --watch` | Index and keep watching for file changes |
| `doc-chat add PATH` | Index a single file or directory (one-shot) |
| `doc-chat remove PATH` | Remove a file's chunks from the index |
| `doc-chat query "question"` | One-shot query, streams answer to stdout |
| `doc-chat query "question" --n 8` | Retrieve 8 chunks instead of the default 5 |
| `doc-chat tui` | Launch the Textual terminal UI |
| `doc-chat serve` | Launch the web UI (default: http://localhost:8420) |
| `doc-chat serve --port 9000 --host 0.0.0.0` | Custom host/port |
| `doc-chat status` | Show index stats, model info, Ollama status |
| `doc-chat models` | List available Ollama models |
| `doc-chat clear` | Wipe the entire index (with confirmation) |

**Global flags** (work with any command):

```
--data-dir PATH       Override storage location (default: ~/.local/share/doc-chat)
--config PATH         Config file path
--ollama-host URL     Override Ollama host (default: http://127.0.0.1:11434)
--version             Show version and GitHub link
```

---

## Supported File Types

| Category | Extensions |
|----------|-----------|
| Text | `.txt` |
| Markdown | `.md`, `.markdown` |
| PDF | `.pdf` |
| Python | `.py` |
| JavaScript / TypeScript | `.js`, `.ts`, `.jsx`, `.tsx` |
| Go | `.go` |
| Rust | `.rs` |
| Java | `.java` |
| C / C++ | `.c`, `.cpp`, `.h`, `.hpp` |
| Ruby | `.rb` |
| PHP | `.php` |
| Shell | `.sh` |
| Lua | `.lua` |
| SQL | `.sql` |
| Config / Data | `.yaml`, `.yml`, `.json`, `.toml` |

Unsupported extensions are silently skipped. The following directories are always ignored: `node_modules`, `.git`, `__pycache__`, `venv`, `.venv`, `dist`, `build`.

---

## Configuration

Place `.doc-chat.toml` in your project directory, or at `~/.config/doc-chat/config.toml` for a global default. All settings are optional — the defaults work out of the box.

```toml
[doc-chat]
data_dir = "~/.local/share/doc-chat"
ollama_host = "http://127.0.0.1:11434"
embed_model = "nomic-embed-text"
chat_model = ""              # empty = auto-detect first available model
chunk_size_tokens = 512      # target tokens per chunk
chunk_overlap_tokens = 50    # overlap between consecutive chunks
n_results = 5                # chunks retrieved per query
conversation_history_length = 5   # previous exchanges to include

[doc-chat.watch]
debounce_seconds = 2.0
ignore_patterns = ["node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build"]
```

Config file search order: `--config` flag → `.doc-chat.toml` in current directory → `~/.config/doc-chat/config.toml`.

---

## How It Works

```
Your documents (PDF, MD, code, txt)
          │
          ▼
    Load & extract text
          │
          ▼
    Split into chunks (512 tokens, 50-token overlap)
          │
          ▼
    Embed each chunk → vector  (nomic-embed-text via Ollama)
          │
          ▼
    Store in ChromaDB (persisted to ~/.local/share/doc-chat/chroma/)
          │
          ▼  ← (indexing done)

    Your question
          │
          ▼
    Embed question → vector
          │
          ▼
    Cosine similarity search → top-5 matching chunks
          │
          ▼
    Build prompt: system instructions + retrieved chunks + question
          │
          ▼
    Stream to Ollama chat model (llama3.2 / mistral / etc.)
          │
          ▼
    Answer with [source: filename] citations, streamed live
```

**Change detection:** Every file is hashed with SHA-256 before indexing. Re-running `doc-chat index` on an unchanged directory completes in milliseconds — only new or modified files are re-embedded.

---

## FAQ

**Does this send my documents to the internet?**
No. Everything runs locally. Ollama runs on `127.0.0.1`, ChromaDB is a local file on disk. No telemetry, no cloud calls, no API keys.

**What happens if I ask about something not in my documents?**
The system prompt instructs the model to say it doesn't know rather than guess. You'll get a clear response like *"The provided context doesn't contain information about X."*

**Can I use a different embedding model?**
Yes — set `embed_model` in `.doc-chat.toml`. Any model supported by `ollama embeddings` works. Note: if you change the embedding model, you must re-index everything (`doc-chat clear && doc-chat index PATH`) because embeddings from different models are not compatible.

**Can I index multiple directories?**
Run `doc-chat index` once for each directory — all chunks land in the same ChromaDB collection and are searched together. Use `--watch` on each if you want auto-reindexing.

**How large can my document set be?**
ChromaDB handles millions of vectors. Practically, the limit is your RAM for search and your disk for storage. A 10,000-page PDF corpus typically produces ~50,000 chunks and uses ~200–500 MB of storage.

**Does it support follow-up questions?**
Yes. The TUI and web UI maintain conversation history (last 5 exchanges by default, configurable). Each new question still performs a fresh retrieval against your documents rather than relying only on chat history.

**Can I run the web UI on a server and access it remotely?**
Yes: `doc-chat serve --host 0.0.0.0 --port 8420`. Be careful about exposing it publicly — there is no authentication. For remote access, use SSH tunneling or put it behind a reverse proxy with auth.

**My GPU isn't being used — why?**
Ollama manages GPU detection. Run `ollama run llama3.2` in a terminal and check the output for GPU layers. If it shows `cpu`, install the CUDA/ROCm drivers for your GPU, then reinstall Ollama.

**How do I update the index when files change?**
Run `doc-chat index PATH` again — it only re-embeds changed files. Or use `doc-chat index PATH --watch` to auto-update in the background.

**Can I use this offline / on an air-gapped machine?**
Yes, completely. After pulling models with `ollama pull`, everything works without any network connection.

**The TUI is blank / not rendering correctly.**
Make sure your terminal supports 256 colors and Unicode. Try `export TERM=xterm-256color`. The TUI is built with [Textual](https://textual.textualize.io) and works best in modern terminals (kitty, alacritty, iTerm2, Windows Terminal).

---

## Troubleshooting

### Ollama not running
```
Error: Cannot connect to Ollama at http://127.0.0.1:11434
```
```bash
ollama serve                  # foreground
systemctl start ollama        # systemd (Linux)
brew services start ollama    # macOS
```

### Embedding model not found
```
Model 'nomic-embed-text' not found. Run: ollama pull nomic-embed-text
```
```bash
ollama pull nomic-embed-text
```

### No chat model available
```bash
ollama pull llama3.2     # fast, 2GB
ollama pull mistral      # 4GB, strong reasoning
```

### Slow embeddings on CPU
First-run indexing on CPU is slow (~1–5s per chunk). This is normal.

- GPU acceleration: Ollama auto-detects CUDA/Metal/ROCm — ensure drivers are installed
- Reduce `chunk_size_tokens = 256` for 2× faster embeddings with slightly less context
- `nomic-embed-text` is already one of the fastest local embedding models

### PDF shows no text
Scanned PDFs (image-only) produce no extractable text. Pre-process with OCR:
```bash
pip install ocrmypdf
ocrmypdf scanned.pdf searchable.pdf
doc-chat add searchable.pdf
```

### Answers feel generic or miss context
- Try `--n 8` to retrieve more chunks per query: `doc-chat query "..." --n 8`
- Reduce `chunk_size_tokens` to 256 for finer-grained retrieval
- Use a larger chat model: `ollama pull llama3.1:8b`

### Index corruption / ChromaDB errors
```bash
doc-chat clear
doc-chat index ~/your/documents
```

### Port already in use
```bash
doc-chat serve --port 9000
```

---

## Architecture

```
doc-chat-local/
├── doc_chat/
│   ├── config.py          Config loading (TOML + defaults)
│   ├── cli.py             All CLI subcommands (argparse)
│   ├── watcher.py         Filesystem watcher (watchdog)
│   ├── ingest/
│   │   ├── loaders.py     File → text extraction (txt/md/pdf/code)
│   │   ├── chunker.py     Text → chunks (tiktoken-aware)
│   │   └── indexer.py     Orchestrates load→chunk→embed→store
│   ├── store/
│   │   └── vectordb.py    ChromaDB wrapper (persist, query, stats)
│   ├── llm/
│   │   ├── ollama_client.py  Async Ollama API (embed, chat stream)
│   │   └── rag.py            RAG pipeline (retrieval + prompt + stream)
│   ├── tui/app.py         Textual TUI
│   └── web/
│       ├── server.py      FastAPI + SSE endpoints
│       └── static/        Vanilla JS/CSS web UI
└── tests/                 pytest suite (loaders + chunker)
```

Storage layout:
```
~/.local/share/doc-chat/
├── chroma/        ChromaDB vector store
└── state.toml     Last indexed path
```

---

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

---

## Support

If doc-chat-local saves you time or you just like the project, a GitHub star goes a long way — it helps others find it.

⭐ **[Star on GitHub](https://github.com/dilates)**

If you'd like to support development directly, donations are appreciated:

**Litecoin (LTC)**
```
LZkNEPvTt9MhGTHuYvhsGSPqw91odZRX4j
```

---

## License

MIT — do whatever you want with it.
 