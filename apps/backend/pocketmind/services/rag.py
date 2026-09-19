"""Document ingestion: parse, chunk, index.

Documents are split into overlapping passages before indexing so retrieval
returns the paragraph that answers the question rather than the first 2 KB of
whatever file happened to match. Content is stored on the drive only.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pocketmind.logs import get_logger
from pocketmind.services.data import PocketDatabase

log = get_logger("rag")

TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".log",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".ps1", ".sql", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".html", ".css",
}
STRUCTURED_SUFFIXES = {".csv", ".tsv", ".json"}
BINARY_SUFFIXES = {".pdf", ".docx"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | STRUCTURED_SUFFIXES | BINARY_SUFFIXES

_PARAGRAPH = re.compile(r"\n\s*\n")
_WHITESPACE = re.compile(r"[ \t]+")

#: Folders that are never worth indexing when importing a project tree.
_SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".cache", ".idea", ".vscode", "site-packages",
}


class UnsupportedDocument(ValueError):
    """The file type cannot be read as text."""


@dataclass
class IngestResult:
    document_id: int | None
    filename: str
    chunk_count: int
    skipped_reason: str | None = None


def extract_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf(data)
    if suffix == ".docx":
        return _extract_docx(data)
    if suffix == ".json":
        return _extract_json(data)
    if suffix in {".csv", ".tsv"}:
        return _extract_delimited(data, delimiter="\t" if suffix == ".tsv" else ",")
    if suffix in TEXT_SUFFIXES:
        return data.decode("utf-8", errors="replace")

    raise UnsupportedDocument(
        f"PocketMind cannot read {suffix or 'files without an extension'} yet. "
        f"Supported types: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
    )


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise UnsupportedDocument("PDF support needs the pypdf package. Reinstall PocketMind's requirements.") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise UnsupportedDocument("This PDF could not be read. It may be scanned images or password protected.") from exc
    text = "\n\n".join(page.strip() for page in pages if page.strip())
    if not text.strip():
        raise UnsupportedDocument(
            "This PDF contains no selectable text. Scanned documents need OCR, which PocketMind does not do yet."
        )
    return text


def _extract_docx(data: bytes) -> str:
    """Read paragraph text straight out of the Word package.

    A .docx is a zip of XML, so the standard library is enough and PocketMind
    avoids another dependency.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            xml = package.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise UnsupportedDocument("This Word document could not be read.") from exc

    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    if not text.strip():
        raise UnsupportedDocument("This Word document contains no readable text.")
    return text


def _extract_json(data: bytes) -> str:
    try:
        parsed = json.loads(data.decode("utf-8", errors="replace"))
    except ValueError:
        return data.decode("utf-8", errors="replace")
    return json.dumps(parsed, indent=2, ensure_ascii=False)


def _extract_delimited(data: bytes, *, delimiter: str) -> str:
    """Render rows as ``column: value`` lines so retrieval keeps the headers."""
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        rows = list(reader)
    except csv.Error:
        return text
    if not rows:
        return ""
    header, *body = rows
    if not body:
        return delimiter.join(header)
    lines = []
    for row in body:
        pairs = [f"{name}: {value}" for name, value in zip(header, row, strict=False) if value.strip()]
        if pairs:
            lines.append(" | ".join(pairs))
    return "\n".join(lines)


def chunk_text(text: str, *, size: int = 900, overlap: int = 150) -> list[str]:
    """Split on paragraph boundaries, packing up to ``size`` characters each."""
    normalised = _WHITESPACE.sub(" ", text).strip()
    if not normalised:
        return []
    overlap = min(overlap, max(size // 2, 0))

    paragraphs = [part.strip() for part in _PARAGRAPH.split(normalised) if part.strip()]
    if not paragraphs:
        paragraphs = [normalised]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        # A single oversized paragraph is cut on whitespace rather than mid-word.
        while len(paragraph) > size:
            head, paragraph = _split_at(paragraph, size)
            chunks.append(head)
        if not current:
            current = paragraph
        elif len(current) + len(paragraph) + 1 <= size:
            current = f"{current}\n{paragraph}"
        else:
            chunks.append(current)
            current = f"{current[-overlap:]} {paragraph}".strip() if overlap else paragraph
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def _split_at(text: str, size: int) -> tuple[str, str]:
    cut = text.rfind(" ", 0, size)
    if cut <= size // 2:
        cut = size
    return text[:cut].strip(), text[cut:].strip()


def ingest(
    database: PocketDatabase,
    filename: str,
    data: bytes,
    *,
    source_path: str | None = None,
    chunk_size: int = 900,
    chunk_overlap: int = 150,
) -> IngestResult:
    """Index one document. Re-importing an unchanged file is a no-op."""
    digest = hashlib.sha256(data).hexdigest()
    if database.document_exists(digest):
        return IngestResult(None, filename, 0, skipped_reason="This exact file is already in your knowledge base.")

    text = extract_text(filename, data)
    chunks = chunk_text(text, size=chunk_size, overlap=chunk_overlap)
    if not chunks:
        return IngestResult(None, filename, 0, skipped_reason="No readable text was found in this file.")

    document_id = database.add_document(filename, digest, len(data), chunks, source_path=source_path)
    log.info("Indexed %s into %d passages", filename, len(chunks))
    return IngestResult(document_id, filename, len(chunks))


def import_folder(
    database: PocketDatabase,
    folder: Path,
    *,
    recursive: bool = True,
    chunk_size: int = 900,
    chunk_overlap: int = 150,
    max_file_bytes: int = 32 * 1024**2,
) -> list[IngestResult]:
    """Index every supported file in a folder, skipping the obvious noise."""
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder} is not a folder PocketMind can read.")

    results: list[IngestResult] = []
    walker = folder.rglob("*") if recursive else folder.glob("*")
    for path in sorted(walker):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS or part.startswith(".") for part in path.relative_to(folder).parts[:-1]):
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                results.append(IngestResult(None, path.name, 0, skipped_reason="File is too large to index."))
                continue
            data = path.read_bytes()
        except OSError as exc:
            results.append(IngestResult(None, path.name, 0, skipped_reason=f"Could not read file ({exc.strerror})."))
            continue
        try:
            results.append(
                ingest(
                    database,
                    path.name,
                    data,
                    source_path=str(path),
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
            )
        except UnsupportedDocument as exc:
            results.append(IngestResult(None, path.name, 0, skipped_reason=str(exc)))
    return results
