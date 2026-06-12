from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".sh", ".lua",
    ".sql", ".yaml", ".yml", ".json", ".toml",
}
PDF_EXTENSIONS = {".pdf"}

SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | CODE_EXTENSIONS | PDF_EXTENSIONS

EXTENSION_TO_LANGUAGE = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "javascript", ".tsx": "typescript", ".go": "go",
    ".rs": "rust", ".java": "java", ".c": "c", ".cpp": "cpp",
    ".h": "c", ".hpp": "cpp", ".rb": "ruby", ".php": "php",
    ".sh": "bash", ".lua": "lua", ".sql": "sql", ".yaml": "yaml",
    ".yml": "yaml", ".json": "json", ".toml": "toml",
}


@dataclass
class LoadedDocument:
    path: Path
    content: str
    doc_type: str
    language: str | None
    metadata: dict
    load_errors: list[str] = field(default_factory=list)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _strip_frontmatter(text: str) -> tuple[str, dict]:
    frontmatter: dict = {}
    if not text.startswith("---"):
        return text, frontmatter
    end = text.find("\n---", 3)
    if end == -1:
        return text, frontmatter
    fm_block = text[3:end].strip()
    for line in fm_block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            frontmatter[k.strip()] = v.strip()
    return text[end + 4:].lstrip("\n"), frontmatter


def _load_text(path: Path) -> LoadedDocument:
    content = _read_text(path)
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        body, fm = _strip_frontmatter(content)
        return LoadedDocument(
            path=path,
            content=body,
            doc_type="markdown",
            language=None,
            metadata={"frontmatter": fm},
        )
    return LoadedDocument(
        path=path,
        content=content,
        doc_type="text",
        language=None,
        metadata={},
    )


def _load_pdf(path: Path) -> LoadedDocument:
    errors: list[str] = []
    try:
        from pypdf import PdfReader
    except ImportError:
        return LoadedDocument(
            path=path, content="", doc_type="pdf", language=None,
            metadata={}, load_errors=["pypdf not installed — cannot read PDFs"],
        )

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return LoadedDocument(
            path=path, content="", doc_type="pdf", language=None,
            metadata={}, load_errors=[f"Failed to open PDF: {exc}"],
        )

    if reader.is_encrypted:
        return LoadedDocument(
            path=path, content="", doc_type="pdf", language=None,
            metadata={}, load_errors=[f"Skipping encrypted PDF: {path.name}"],
        )

    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
            text = re.sub(r"\s{3,}", "  ", text)
            text = re.sub(r"\f", "\n", text)
            pages.append(text.strip())
        except Exception as exc:
            errors.append(f"Page {i + 1} extraction error: {exc}")

    full_text = "\n\n".join(p for p in pages if p)
    if not full_text.strip():
        errors.append(
            f"No text extracted from {path.name} — it may be a scanned image PDF. "
            "Consider running OCR (e.g. ocrmypdf) first."
        )

    return LoadedDocument(
        path=path,
        content=full_text,
        doc_type="pdf",
        language=None,
        metadata={"page_count": len(reader.pages), "pages": pages},
        load_errors=errors,
    )


def _load_code(path: Path) -> LoadedDocument:
    content = _read_text(path)
    language = EXTENSION_TO_LANGUAGE.get(path.suffix.lower())
    return LoadedDocument(
        path=path,
        content=content,
        doc_type="code",
        language=language,
        metadata={"filename": path.name, "language": language},
    )


_LOADERS = {
    **{ext: _load_text for ext in TEXT_EXTENSIONS},
    **{ext: _load_code for ext in CODE_EXTENSIONS},
    **{ext: _load_pdf for ext in PDF_EXTENSIONS},
}


def load_file(path: Path) -> LoadedDocument | None:
    suffix = path.suffix.lower()
    loader = _LOADERS.get(suffix)
    if loader is None:
        log.debug("Unsupported extension %s, skipping %s", suffix, path)
        return None
    try:
        return loader(path)
    except Exception as exc:
        log.error("Failed to load %s: %s", path, exc)
        return LoadedDocument(
            path=path, content="", doc_type="unknown", language=None,
            metadata={}, load_errors=[str(exc)],
        )
