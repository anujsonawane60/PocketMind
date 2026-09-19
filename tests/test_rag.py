"""Document parsing, chunking, and indexing."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from pocketmind.services import rag
from pocketmind.services.data import PocketDatabase


def test_chunks_respect_the_size_limit():
    text = "\n\n".join(f"Paragraph number {index}. " * 12 for index in range(40))
    chunks = rag.chunk_text(text, size=500, overlap=80)
    assert chunks
    assert all(len(chunk) <= 700 for chunk in chunks)  # size plus one overlap tail


def test_chunks_overlap_so_facts_are_not_split_away():
    text = "\n\n".join(f"Sentence {index} carries meaning." for index in range(60))
    chunks = rag.chunk_text(text, size=300, overlap=100)
    assert len(chunks) > 1
    # Consecutive chunks should share some text.
    assert any(chunks[index][-40:] in chunks[index + 1] for index in range(len(chunks) - 1))


def test_a_single_huge_paragraph_is_split_on_whitespace():
    chunks = rag.chunk_text("word " * 2000, size=400, overlap=0)
    assert len(chunks) > 1
    assert all(not chunk.startswith("ord") for chunk in chunks)


def test_empty_text_produces_no_chunks():
    assert rag.chunk_text("   \n\n  ") == []


def test_markdown_and_code_are_read_as_text():
    assert "def hello" in rag.extract_text("main.py", b"def hello():\n    pass\n")
    assert "# Title" in rag.extract_text("notes.md", b"# Title\n\nBody")


def test_csv_keeps_its_column_names():
    data = b"name,role\nAlex,engineer\nSam,designer\n"
    text = rag.extract_text("team.csv", data)
    assert "name: Alex" in text
    assert "role: designer" in text


def test_json_is_pretty_printed():
    text = rag.extract_text("config.json", json.dumps({"key": "value"}).encode())
    assert '"key": "value"' in text


def test_docx_text_is_extracted_with_the_standard_library():
    document_xml = (
        '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
        "<w:p><w:r><w:t>First paragraph.</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Second paragraph.</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("word/document.xml", document_xml)
    text = rag.extract_text("report.docx", buffer.getvalue())
    assert "First paragraph." in text
    assert "Second paragraph." in text


def test_unsupported_types_are_refused_clearly():
    with pytest.raises(rag.UnsupportedDocument) as error:
        rag.extract_text("photo.heic", b"\x00\x01")
    assert "cannot read" in str(error.value)


def test_ingest_indexes_and_is_searchable(database: PocketDatabase):
    result = rag.ingest(database, "notes.md", b"PocketMind keeps documents on the drive.\n" * 5)
    assert result.document_id is not None
    assert result.chunk_count >= 1
    assert database.search_chunks("documents drive")


def test_ingesting_the_same_file_twice_is_skipped(database: PocketDatabase):
    payload = b"Identical content for both attempts."
    assert rag.ingest(database, "a.txt", payload).document_id is not None
    second = rag.ingest(database, "a-copy.txt", payload)
    assert second.document_id is None
    assert "already" in second.skipped_reason


def test_folder_import_skips_noise_directories(tmp_path, database: PocketDatabase):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "keep.md").write_text("Retrieval notes about embeddings.", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.js").write_text("module.exports = {}", encoding="utf-8")
    (tmp_path / "photo.heic").write_bytes(b"\x00")

    results = rag.import_folder(database, tmp_path)
    indexed = [item.filename for item in results if item.document_id is not None]
    assert "keep.md" in indexed
    assert "skip.js" not in indexed
    assert "photo.heic" not in indexed


def test_folder_import_reports_a_missing_folder(tmp_path, database: PocketDatabase):
    with pytest.raises(FileNotFoundError):
        rag.import_folder(database, tmp_path / "nope")
