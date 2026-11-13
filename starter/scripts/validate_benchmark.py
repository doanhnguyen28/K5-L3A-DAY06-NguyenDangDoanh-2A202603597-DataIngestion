import csv
import json
import sys
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
sys.path.insert(0, str(STARTER))
from src.ingestion import compact  

PDF = STARTER / "data" / "100pages.pdf"
INVENTORY = ROOT / "data" / "page_inventory.csv"
QUESTIONS = ROOT / "benchmark" / "questions.jsonl"
SOURCE_ID = "pof-ch1-3"
TEST_SECTIONS = {"1.6", "2.5", "3.3"}  
REQUIRED = ["id", "split", "type", "question", "expected_answer",
            "gold_source_id", "gold_page", "evidence_quote"]
FILTER_FIELDS = {"chapter"}


def main() -> int:
    errors: list[str] = []
    with INVENTORY.open(encoding="utf-8") as f:
        inventory = {int(r["pdf_page"]): r for r in csv.DictReader(f)}
    counted = {p for p, r in inventory.items() if r["counted"] == "True"}
    chapters = {inventory[p]["chapter"] for p in counted}
    reader = PdfReader(PDF)
    page_cache: dict[int, str] = {}

    def page_text(page: int) -> str:
        if page not in page_cache:
            page_cache[page] = compact(reader.pages[page - 1].extract_text() or "")
        return page_cache[page]

    lines = [ln for ln in QUESTIONS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    questions = []
    for n, line in enumerate(lines, start=1):
        try:
            questions.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"line {n}: invalid JSON ({exc})")

    ids = Counter(q.get("id") for q in questions)
    errors += [f"{i}: duplicate id" for i, c in ids.items() if c > 1]
    splits = Counter(q.get("split") for q in questions)
    if len(questions) < 20:
        errors.append(f"only {len(questions)} questions (need >= 20)")
    if splits["dev"] < 15 or splits["test"] < 5:
        errors.append(f"split counts dev={splits['dev']} test={splits['test']} (need >=15 / >=5)")

    for q in questions:
        qid = q.get("id", "?")
        missing = [k for k in REQUIRED if q.get(k) in (None, "", [])]
        if missing:
            errors.append(f"{qid}: missing/empty fields {missing}")
            continue
        if q["split"] not in {"dev", "test"}:
            errors.append(f"{qid}: split must be dev/test")
        if q["gold_source_id"] != SOURCE_ID:
            errors.append(f"{qid}: unknown gold_source_id {q['gold_source_id']}")
        gold = q["gold_page"] if isinstance(q["gold_page"], list) else [q["gold_page"]]
        bad = [p for p in gold if p not in counted]
        if bad:
            errors.append(f"{qid}: gold_page {bad} is not a counted content page")
            continue

        evidence = [(gold[0], q["evidence_quote"])]
        evidence += [(a["page"], a["quote"]) for a in q.get("alt_evidence") or []]
        for page, quote in evidence:
            if page not in gold:
                errors.append(f"{qid}: evidence page {page} not listed in gold_page")
            elif compact(quote) not in page_text(page):
                errors.append(f"{qid}: quote not found on page {page}: {quote[:60]!r}...")
        unbacked = set(gold) - {p for p, _ in evidence}
        if unbacked:
            errors.append(f"{qid}: gold pages {sorted(unbacked)} have no evidence quote")

        flt = q.get("filter")
        if flt:
            if set(flt) - FILTER_FIELDS:
                errors.append(f"{qid}: unsupported filter fields {set(flt) - FILTER_FIELDS}")
            elif flt["chapter"] not in chapters:
                errors.append(f"{qid}: filter chapter {flt['chapter']!r} not in metadata {sorted(chapters)}")
            elif any(inventory[p]["chapter"] != flt["chapter"] for p in gold):
                errors.append(f"{qid}: a gold page is outside filter chapter {flt['chapter']}")

        section = inventory[gold[0]]["section"]
        if q["split"] == "test" and section not in TEST_SECTIONS:
            errors.append(f"{qid}: test question from non-test section {section}")
        if q["split"] == "dev" and section in TEST_SECTIONS:
            errors.append(f"{qid}: dev question from test section {section} (leakage)")

    filtered = [q for q in questions if q.get("filter")]
    if len(filtered) < 3 or not any(q.get("split") == "test" for q in filtered):
        errors.append(f"need >=3 filter questions with >=1 in test (have {len(filtered)})")

    print(f"Questions: {len(questions)} | dev={splits['dev']} test={splits['test']}")
    for split in ("dev", "test"):
        types = Counter(q.get("type") for q in questions if q.get("split") == split)
        chs = Counter(inventory[(q["gold_page"] if isinstance(q["gold_page"], list) else [q["gold_page"]])[0]]["chapter"]
                      for q in questions if q.get("split") == split and q.get("gold_page"))
        print(f"  {split}: types={dict(types)} chapters={dict(sorted(chs.items()))}")
    print(f"  filter questions: {[q['id'] for q in filtered]}")
    if errors:
        print(f"\n{len(errors)} ERROR(S):")
        for e in errors:
            print("  -", e)
        return 1
    print("\nOK: all evidence verified on its gold page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
