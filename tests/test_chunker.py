"""Tests for doc_chat.ingest.chunker."""
from pathlib import Path

import pytest

from doc_chat.ingest.loaders import load_file
from doc_chat.ingest.chunker import chunk_document, Chunk

FIXTURES = Path(__file__).parent / "fixtures"


def test_chunk_markdown_produces_chunks():
    doc = load_file(FIXTURES / "sample.md")
    chunks = chunk_document(doc)
    assert len(chunks) > 0
    for c in chunks:
        assert isinstance(c, Chunk)
        assert c.text.strip()
        assert c.id
        assert c.source_path == str(FIXTURES / "sample.md")
        assert c.doc_type == "markdown"


def test_chunk_ids_deterministic():
    doc = load_file(FIXTURES / "sample.md")
    chunks1 = chunk_document(doc)
    chunks2 = chunk_document(doc)
    assert [c.id for c in chunks1] == [c.id for c in chunks2]


def test_chunk_python_extracts_functions():
    doc = load_file(FIXTURES / "sample.py")
    chunks = chunk_document(doc)
    texts = "\n".join(c.text for c in chunks)
    assert "def add" in texts
    assert "def multiply" in texts
    assert "class Calculator" in texts


def test_chunk_python_includes_filename():
    doc = load_file(FIXTURES / "sample.py")
    chunks = chunk_document(doc)
    for c in chunks:
        assert "sample.py" in c.text


def test_chunk_text(tmp_path):
    f = tmp_path / "text.txt"
    f.write_text("First paragraph.\n\nSecond paragraph.\n\nThird paragraph.")
    doc = load_file(f)
    chunks = chunk_document(doc)
    assert len(chunks) >= 1
    all_text = " ".join(c.text for c in chunks)
    assert "First" in all_text
    assert "Second" in all_text


def test_chunk_empty_document(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    doc = load_file(f)
    chunks = chunk_document(doc)
    assert chunks == []


def test_chunk_size_limit(tmp_path):
    long_text = "word " * 2000
    f = tmp_path / "long.txt"
    f.write_text(long_text)
    doc = load_file(f)
    chunks = chunk_document(doc, max_tokens=512, overlap_tokens=50)
    for c in chunks:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        assert len(enc.encode(c.text)) <= 512 + 20
