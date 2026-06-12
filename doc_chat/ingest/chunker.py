from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import tiktoken

if TYPE_CHECKING:
    from doc_chat.ingest.loaders import LoadedDocument

_enc = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text, disallowed_special=()))


@dataclass
class Chunk:
    id: str
    text: str
    source_path: str
    doc_type: str
    metadata: dict = field(default_factory=dict)


def _make_id(source_path: str, index: int, text: str) -> str:
    h = hashlib.sha256(f"{source_path}:{index}:{text}".encode()).hexdigest()
    return h[:32]


def _split_by_tokens(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    tokens = _enc.encode(text, disallowed_special=())
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(_enc.decode(chunk_tokens))
        if end == len(tokens):
            break
        start = end - overlap_tokens
    return chunks


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _chunk_text_content(
    text: str,
    source_path: str,
    doc_type: str,
    base_metadata: dict,
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    paragraphs = re.split(r"\n{2,}", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    raw_chunks: list[tuple[str, dict]] = []
    current_parts: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = _count_tokens(para)
        if para_tokens > max_tokens:
            if current_parts:
                raw_chunks.append(("\n\n".join(current_parts), {}))
                current_parts = []
                current_tokens = 0
            for sub in _split_by_tokens(para, max_tokens, overlap_tokens):
                raw_chunks.append((sub, {}))
        elif current_tokens + para_tokens > max_tokens and current_parts:
            raw_chunks.append(("\n\n".join(current_parts), {}))
            current_parts = [para]
            current_tokens = para_tokens
        else:
            current_parts.append(para)
            current_tokens += para_tokens

    if current_parts:
        raw_chunks.append(("\n\n".join(current_parts), {}))

    result: list[Chunk] = []
    for i, (txt, extra_meta) in enumerate(raw_chunks):
        meta = {**base_metadata, **extra_meta}
        result.append(Chunk(
            id=_make_id(source_path, i, txt),
            text=txt,
            source_path=source_path,
            doc_type=doc_type,
            metadata=meta,
        ))
    return result


def _chunk_markdown(
    doc: "LoadedDocument",
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    text = doc.content
    source_path = str(doc.path)
    base_meta = {"frontmatter": doc.metadata.get("frontmatter", {})}

    # Split at heading boundaries
    sections = re.split(r"(?m)^(#{1,6}\s+.+)$", text)
    current_heading = ""
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(sections):
        part = sections[i].strip()
        if not part:
            i += 1
            continue
        if re.match(r"^#{1,6}\s+", part):
            current_heading = part
            i += 1
        else:
            blocks.append((current_heading, part))
            i += 1

    result: list[Chunk] = []
    chunk_index = 0
    for heading, body in blocks:
        prefix = f"{heading}\n\n" if heading else ""
        combined = prefix + body
        if _count_tokens(combined) <= max_tokens:
            meta = {**base_meta, "heading": heading}
            result.append(Chunk(
                id=_make_id(source_path, chunk_index, combined),
                text=combined,
                source_path=source_path,
                doc_type="markdown",
                metadata=meta,
            ))
            chunk_index += 1
        else:
            for sub in _chunk_text_content(combined, source_path, "markdown", {**base_meta, "heading": heading}, max_tokens, overlap_tokens):
                sub.id = _make_id(source_path, chunk_index, sub.text)
                result.append(sub)
                chunk_index += 1

    if not result:
        result = _chunk_text_content(text, source_path, "markdown", base_meta, max_tokens, overlap_tokens)
    return result


def _chunk_pdf(
    doc: "LoadedDocument",
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    source_path = str(doc.path)
    pages: list[str] = doc.metadata.get("pages", [])
    if not pages:
        pages = [doc.content]

    result: list[Chunk] = []
    chunk_index = 0
    for page_num, page_text in enumerate(pages, 1):
        page_text = page_text.strip()
        if not page_text:
            continue
        page_meta = {"page_number": page_num, "page_count": len(pages)}
        for sub in _chunk_text_content(page_text, source_path, "pdf", page_meta, max_tokens, overlap_tokens):
            sub.id = _make_id(source_path, chunk_index, sub.text)
            result.append(sub)
            chunk_index += 1
    return result


def _extract_python_units(source: str) -> list[tuple[str, str, int, int]]:
    """Returns list of (name, code_text, start_line, end_line)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    units: list[tuple[str, str, int, int]] = []
    lines = source.splitlines()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, "end_lineno") else node.lineno
            text = "\n".join(lines[start:end])
            units.append((node.name, text, start + 1, end))
    return units


def _chunk_python(
    doc: "LoadedDocument",
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    source_path = str(doc.path)
    content = doc.content
    base_meta = {"filename": doc.path.name, "language": "python"}
    units = _extract_python_units(content)

    result: list[Chunk] = []
    chunk_index = 0

    covered_lines: set[int] = set()
    for name, text, start_line, end_line in units:
        covered_lines.update(range(start_line, end_line + 1))
        prefix = f"# File: {doc.path.name}\n# {type.__name__}: {name}\n"
        full_text = prefix + text
        meta = {**base_meta, "function_or_class": name, "line_start": start_line, "line_end": end_line}

        if _count_tokens(full_text) <= max_tokens:
            result.append(Chunk(
                id=_make_id(source_path, chunk_index, full_text),
                text=full_text,
                source_path=source_path,
                doc_type="code",
                metadata=meta,
            ))
            chunk_index += 1
        else:
            for sub in _split_by_tokens(full_text, max_tokens, overlap_tokens):
                result.append(Chunk(
                    id=_make_id(source_path, chunk_index, sub),
                    text=sub,
                    source_path=source_path,
                    doc_type="code",
                    metadata=meta,
                ))
                chunk_index += 1

    lines = content.splitlines()
    module_lines = [
        (i + 1, line) for i, line in enumerate(lines)
        if (i + 1) not in covered_lines and line.strip()
    ]
    if module_lines:
        module_text = f"# File: {doc.path.name}\n" + "\n".join(line for _, line in module_lines)
        for sub in _split_by_tokens(module_text, max_tokens, overlap_tokens):
            result.append(Chunk(
                id=_make_id(source_path, chunk_index, sub),
                text=sub,
                source_path=source_path,
                doc_type="code",
                metadata={**base_meta, "section": "module-level"},
            ))
            chunk_index += 1

    return result or _chunk_generic_code(doc, max_tokens, overlap_tokens)


def _chunk_generic_code(
    doc: "LoadedDocument",
    max_tokens: int,
    overlap_tokens: int,
    lines_per_chunk: int = 60,
    overlap_lines: int = 10,
) -> list[Chunk]:
    source_path = str(doc.path)
    base_meta = {"filename": doc.path.name, "language": doc.language}
    lines = doc.content.splitlines()
    result: list[Chunk] = []
    chunk_index = 0

    start = 0
    while start < len(lines):
        end = min(start + lines_per_chunk, len(lines))
        # try to break on blank line near end
        for j in range(end - 1, max(start, end - 10), -1):
            if not lines[j].strip():
                end = j + 1
                break
        chunk_lines = lines[start:end]
        text = f"# File: {doc.path.name}\n" + "\n".join(chunk_lines)
        meta = {**base_meta, "line_start": start + 1, "line_end": end}
        result.append(Chunk(
            id=_make_id(source_path, chunk_index, text),
            text=text,
            source_path=source_path,
            doc_type="code",
            metadata=meta,
        ))
        chunk_index += 1
        if end >= len(lines):
            break
        start = end - overlap_lines

    return result


def chunk_document(
    doc: "LoadedDocument",
    max_tokens: int = 512,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    if not doc.content.strip():
        return []

    if doc.doc_type == "markdown":
        return _chunk_markdown(doc, max_tokens, overlap_tokens)
    elif doc.doc_type == "pdf":
        return _chunk_pdf(doc, max_tokens, overlap_tokens)
    elif doc.doc_type == "code":
        if doc.language == "python":
            return _chunk_python(doc, max_tokens, overlap_tokens)
        return _chunk_generic_code(doc, max_tokens, overlap_tokens)
    else:
        return _chunk_text_content(
            doc.content, str(doc.path), doc.doc_type, {}, max_tokens, overlap_tokens
        )
