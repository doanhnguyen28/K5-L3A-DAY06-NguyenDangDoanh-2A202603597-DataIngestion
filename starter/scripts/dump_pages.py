import csv
import sys
from pathlib import Path

from pypdf import PdfReader

STARTER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STARTER))
from src.ingestion import normalize_text  # noqa: E402

PDF = STARTER / "data" / "100pages.pdf"
INVENTORY = STARTER.parent / "data" / "page_inventory.csv"
OUT = STARTER / "results" / "pages_normalized"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(PDF)
    with INVENTORY.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["counted"] == "True"]
    for row in rows:
        page = int(row["pdf_page"])
        text = normalize_text(reader.pages[page - 1].extract_text() or "")
        header = (f"# pdf_page={page} chapter={row['chapter']} section={row['section']} "
                  f"title={row['section_title']} type={row['page_type']}\n\n")
        (OUT / f"p{page:03d}.txt").write_text(header + text + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} pages to {OUT}")


if __name__ == "__main__":
    main()
