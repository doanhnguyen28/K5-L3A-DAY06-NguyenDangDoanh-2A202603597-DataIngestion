"""Page inventory for the corpus: classify every physical PDF page and decide whether it counts.

Usage (from starter/):  python scripts/inventory_pages.py data/100pages.pdf
Output: ../data/page_inventory.csv  (one row per physical page)

Counting rule (decided before building the benchmark):
  counted = explanatory content pages of a section, including Summary and Key Terms.
  excluded = front matter (cover, TOC, licensing, authors), chapter overview (mini TOC),
             exercise sections (Multiple Choice, Review Questions, Problems, Video Activity,
             CFA Institute), and pages whose body is only footnotes/license (< MIN_BODY chars).
"""
import csv
import re
import sys
import unicodedata
from pathlib import Path

from pypdf import PdfReader

HEADER = re.compile(r"^(\d+)\.(\d+)\.(\d+)\s+https://biz\.libretexts\.org/@go/page/(\d+)\s*$")
SECTION_TITLE = re.compile(r"^(\d+)\.(\d+):\s*(.+)$")
EXERCISE = re.compile(r"Multiple Choice|Review Questions|Problems|Video Activity|CFA Institute", re.I)
LICENSE_START = re.compile(r"^This page titled .* is shared under", re.I)
MIN_BODY = 300  # chars of real body text required after removing footnotes/license


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def body_without_notes(lines: list[str]) -> str:
    """Drop the footnotes block and the trailing LibreTexts license sentence."""
    kept = []
    for line in lines:
        if line.strip() == "Footnotes" or LICENSE_START.match(line.strip()):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def main(pdf_path: str) -> None:
    reader = PdfReader(pdf_path)
    titles: dict[str, str] = {}
    rows = []
    for idx, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        text = normalize(raw)
        lines = text.splitlines()
        first = lines[0].strip() if lines else ""
        row = {"pdf_page": idx, "chapter": "", "section": "", "section_page": "",
               "libretexts_page_id": "", "section_title": "", "page_type": "",
               "counted": False, "reason": "", "chars_normalized": len(text),
               "replacement_chars": text.count("�")}
        match = HEADER.match(first)
        if not text:
            row.update(page_type="empty", reason="no extractable text")
        elif "CHAPTER OVERVIEW" in text[:200]:
            row.update(page_type="chapter_overview", reason="chapter table of contents")
            ch = re.search(r"^(\d+):", "\n".join(lines[1:4]), re.M)
            row["chapter"] = ch.group(1) if ch else ""
        elif not match:
            row.update(page_type="front_matter", reason="cover/TOC/licensing/authors")
        else:
            chapter, sec, sec_page, lt_id = match.groups()
            section = f"{chapter}.{sec}"
            for line in lines[1:3]:
                t = SECTION_TITLE.match(line.strip())
                if t and f"{t.group(1)}.{t.group(2)}" == section:
                    titles[section] = t.group(3).strip()
            title = titles.get(section, "")
            body = body_without_notes(lines[1:])
            row.update(chapter=chapter, section=section, section_page=sec_page,
                       libretexts_page_id=lt_id, section_title=title)
            if EXERCISE.search(title):
                row.update(page_type="exercise", reason=f"exercise section: {title}")
            elif len(body) < MIN_BODY:
                row.update(page_type="notes_only", reason=f"footnotes/license only ({len(body)} body chars)")
            else:
                kind = "summary" if "Summary" in title else "key_terms" if "Key T" in title else "content"
                row.update(page_type=kind, counted=True)
        rows.append(row)

    out = Path(__file__).resolve().parents[2] / "data" / "page_inventory.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    counted = [r for r in rows if r["counted"]]
    print(f"Physical pages: {len(rows)} | counted content pages: {len(counted)}")
    for ch in sorted({r['chapter'] for r in counted}):
        pages = [r["pdf_page"] for r in counted if r["chapter"] == ch]
        chars = sum(r["chars_normalized"] for r in counted if r["chapter"] == ch)
        print(f"  chapter {ch}: {len(pages)} pages, {chars} chars -> {pages}")
    by_type: dict[str, list[int]] = {}
    for r in rows:
        if not r["counted"]:
            by_type.setdefault(r["page_type"], []).append(r["pdf_page"])
    for kind, pages in by_type.items():
        print(f"  excluded {kind}: {pages}")
    print(f"  total counted chars: {sum(r['chars_normalized'] for r in counted)}")
    print(f"  pages with U+FFFD replacement chars: {sum(1 for r in rows if r['replacement_chars'])}")
    print(f"Wrote {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/inventory_pages.py <pdf>")
    main(sys.argv[1])
