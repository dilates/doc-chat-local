"""Tests for doc_chat.ingest.loaders."""
from pathlib import Path

import pytest

from doc_chat.ingest.loaders import load_file, LoadedDocument

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_markdown():
    doc = load_file(FIXTURES / "sample.md")
    assert doc is not None
    assert doc.doc_type == "markdown"
    assert doc.language is None
    assert "Introduction" in doc.content
    assert doc.metadata.get("frontmatter", {}).get("title") == "Sample Document"
    assert not doc.load_errors


def test_markdown_frontmatter_stripped():
    doc = load_file(FIXTURES / "sample.md")
    assert doc is not None
    assert "---" not in doc.content.split("\n")[0]


def test_load_python():
    doc = load_file(FIXTURES / "sample.py")
    assert doc is not None
    assert doc.doc_type == "code"
    assert doc.language == "python"
    assert "Calculator" in doc.content
    assert not doc.load_errors


def test_unsupported_extension(tmp_path):
    f = tmp_path / "file.xyz"
    f.write_text("hello")
    doc = load_file(f)
    assert doc is None


def test_load_nonexistent_file(tmp_path):
    doc = load_file(tmp_path / "nonexistent.txt")
    assert doc is not None
    assert doc.load_errors


def test_load_txt(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("Hello world\n\nSecond paragraph.")
    doc = load_file(f)
    assert doc is not None
    assert doc.doc_type == "text"
    assert "Hello world" in doc.content


def test_load_latin1_fallback(tmp_path):
    f = tmp_path / "latin.txt"
    f.write_bytes("caf\xe9".encode("latin-1"))
    doc = load_file(f)
    assert doc is not None
    assert "caf" in doc.content
