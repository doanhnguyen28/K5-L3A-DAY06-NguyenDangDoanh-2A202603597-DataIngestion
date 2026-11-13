from pathlib import Path

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
RESULTS = STARTER / "results"

DOCUMENT_ID = "pof-ch1-3"
PDF_PATH = STARTER / "data" / "100pages.pdf"
SOURCE = "starter/data/100pages.pdf"         
INVENTORY = ROOT / "data" / "page_inventory.csv"
QUESTIONS = ROOT / "benchmark" / "questions.jsonl"

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

STRATEGIES = {
    "A": {"index": "A", "chunker": "fixed", "size": 500, "overlap": 50, "use_filter": False},
    "B": {"index": "B", "chunker": "paragraph", "max_size": 800, "use_filter": False},
    "C": {"index": "B", "chunker": "paragraph", "max_size": 800, "use_filter": True},
}
INDEXES = {"A": STRATEGIES["A"], "B": STRATEGIES["B"]}

FILTERABLE = ("chapter", "section", "page_type", "document_id")
TOP_K = 3
