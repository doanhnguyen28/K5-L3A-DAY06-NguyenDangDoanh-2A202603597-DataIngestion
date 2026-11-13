"""Fixed-size and structure-aware chunking. Chunks never cross page boundaries, so `page` is exact."""
import hashlib
import re

from .models import Chunk, DocumentPage

SHORT_LINE = 110
LIST_ITEM = re.compile(r"^\d+\.\s")
SENTENCE_END = re.compile(r"(?<=[.!?”])\s+")
HEADING_MAX = 80
HEADING_END = re.compile(r"[.!?:;,”)]$")


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _make_chunk(page: DocumentPage, tag: str, idx: int, text: str, start: int, end: int) -> Chunk:
    meta = dict(page.metadata)
    meta.update(char_start=start, char_end=end, content_hash=_content_hash(text))
    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page:03d}:{tag}:c{idx:02d}",
        document_id=page.document_id, source=page.source, page=page.page,
        text=text, metadata=meta,
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Character windows of `size` with `overlap`, ignoring sentence/paragraph structure (baseline)."""
    if not 0 <= overlap < size:
        raise ValueError("require 0 <= overlap < size")
    text, step, chunks = page.text, size - overlap, []
    for idx, start in enumerate(range(0, len(text), step)):
        piece = text[start:start + size]
        if not piece.strip():
            continue
        chunks.append(_make_chunk(page, f"fixed{size}-{overlap}", idx, piece, start, start + len(piece)))
        if start + size >= len(text):
            break
    return chunks


def split_paragraphs(text: str) -> list[tuple[int, int]]:
    """Return (start, end) offsets of paragraphs reconstructed from line lengths."""
    spans, start, pos = [], 0, 0
    lines = text.split("\n")
    for i, line in enumerate(lines):
        end = pos + len(line)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        is_break = (len(line) < SHORT_LINE or not line.strip()
                    or bool(LIST_ITEM.match(nxt)) or i == len(lines) - 1)
        if is_break:
            if text[start:end].strip():
                spans.append((start, end))
            start = end + 1
        pos = end + 1
    merged: list[tuple[int, int]] = []
    carry = None
    for s, e in spans:
        if carry is not None:
            s, carry = carry, None
        piece = text[s:e].strip()
        if len(piece) < HEADING_MAX and not HEADING_END.search(piece) and (s, e) != spans[-1]:
            carry = s
            continue
        merged.append((s, e))
    return merged


def _split_long(text: str, base: int, max_size: int) -> list[tuple[int, int]]:
    """Split an oversized paragraph at sentence ends; hard-cut only a single over-long sentence."""
    spans, start = [], 0
    cut_points = [m.end() for m in SENTENCE_END.finditer(text)] + [len(text)]
    last = 0
    for cp in cut_points:
        if cp - start > max_size and last > start:
            spans.append((base + start, base + last))
            start = last
        last = cp
    while len(text) - start > max_size:          # one sentence longer than max_size
        spans.append((base + start, base + start + max_size))
        start += max_size
    spans.append((base + start, base + len(text)))
    return spans


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Group consecutive paragraphs up to `max_size` chars; headings stay with the following text."""
    text = page.text
    units: list[tuple[int, int]] = []
    for s, e in split_paragraphs(text):
        units.extend(_split_long(text[s:e], s, max_size) if e - s > max_size else [(s, e)])
    chunks, cur_s, cur_e, idx = [], None, None, 0
    for s, e in units:
        if cur_s is None:
            cur_s, cur_e = s, e
        elif e - cur_s <= max_size:
            cur_e = e
        else:
            chunks.append(_make_chunk(page, f"para{max_size}", idx, text[cur_s:cur_e].strip(), cur_s, cur_e))
            idx += 1
            cur_s, cur_e = s, e
    if cur_s is not None and text[cur_s:cur_e].strip():
        chunks.append(_make_chunk(page, f"para{max_size}", idx, text[cur_s:cur_e].strip(), cur_s, cur_e))
    return chunks
