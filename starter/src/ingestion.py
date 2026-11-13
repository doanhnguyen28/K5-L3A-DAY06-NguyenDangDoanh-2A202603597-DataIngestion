"""Read and normalize source data."""
import csv
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage

_ICON_CHARS = {"": ""}

PAGE_HEADER = re.compile(r"^\d+\.\d+\.\d+\s+https://biz\.libretexts\.org/@go/page/\d+$")
LICENSE_START = re.compile(r"^This page titled .* is shared under", re.I)


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace without discarding paragraph/line structure.

    - NFC Unicode normalization (curly quotes are kept as-is)
    - drop known private-use icon glyphs
    - collapse runs of spaces/tabs, strip spaces at line ends
    - collapse 3+ newlines into one blank line
    Mid-word spaces produced by the PDF export (e.g. "bud get") are NOT repaired:
    repairing them heuristically could corrupt correct words. Logged as a limitation.
    """
    text = unicodedata.normalize("NFC", text)
    for bad, repl in _ICON_CHARS.items():
        text = text.replace(bad, repl)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t ]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def compact(text: str) -> str:
    return " ".join(normalize_text(text).split())


def strip_boilerplate(text: str) -> tuple[str, list[str]]:
    lines = text.split("\n")
    removed = []
    if lines and PAGE_HEADER.match(lines[0]):
        removed.append("header")
        lines = lines[1:]
    for i, line in enumerate(lines):
        if line == "Footnotes" or LICENSE_START.match(line):
            removed.append("footnotes" if line == "Footnotes" else "license")
            lines = lines[:i]
            break
    return "\n".join(lines).strip(), removed


def load_inventory(path: Path) -> dict[int, dict]:
    with path.open(encoding="utf-8") as f:
        return {int(r["pdf_page"]): r for r in csv.DictReader(f)}


def load_pdf(path: Path, document_id: str, source: str,
             inventory: dict[int, dict]) -> tuple[list[DocumentPage], list[dict]]:
    """Extract every counted physical page, keep page number, source and source-derived metadata.

    Metadata (chapter, section, section_title, page_type) comes from the page inventory,
    which was parsed from each page's own LibreTexts header line. Pages with no text,
    empty pages after cleaning, and every removal are recorded in the returned log.
    """
    reader = PdfReader(path)
    pages: list[DocumentPage] = []
    log: list[dict] = []
    for number, page in enumerate(reader.pages, start=1):
        meta = inventory.get(number)
        raw = page.extract_text() or ""
        if not raw.strip():
            log.append({"page": number, "level": "error", "event": "no_text", "detail": "no extractable text"})
            continue
        if not meta or meta["counted"] != "True":
            log.append({"page": number, "level": "info", "event": "skipped",
                        "detail": meta["reason"] if meta else "not in inventory"})
            continue
        icons = sum(raw.count(c) for c in _ICON_CHARS)
        text, removed = strip_boilerplate(normalize_text(raw))
        if icons:
            log.append({"page": number, "level": "warning", "event": "icon_glyph_removed", "detail": f"{icons}x U+F5DC"})
        if removed:
            log.append({"page": number, "level": "info", "event": "boilerplate_removed", "detail": "+".join(removed)})
        if not text:
            log.append({"page": number, "level": "error", "event": "empty_after_cleaning", "detail": ""})
            continue
        pages.append(DocumentPage(
            document_id=document_id, source=source, page=number, text=text,
            metadata={"chapter": meta["chapter"], "section": meta["section"],
                      "section_title": meta["section_title"], "page_type": meta["page_type"]},
        ))
    return pages, log
