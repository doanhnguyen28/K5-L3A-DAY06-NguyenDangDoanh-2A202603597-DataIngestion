"""Single place for corpus, model and strategy settings (kept identical across A/B/C)."""
from pathlib import Path

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
RESULTS = STARTER / "results"

# Corpus (see ../data/manifest.csv)
DOCUMENT_ID = "pof-ch1-3"
PDF_PATH = STARTER / "data" / "100pages.pdf"
SOURCE = "starter/data/100pages.pdf"          # repo-relative path stored as `source`
INVENTORY = ROOT / "data" / "page_inventory.csv"
QUESTIONS = ROOT / "benchmark" / "questions.jsonl"

# Embedding model: same model, same query/document handling for every strategy
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Strategies. `index` = rows stored in the vector table under that strategy name.
# C re-uses index B, so B and C differ ONLY in applying the metadata filter.
STRATEGIES = {
    "A": {"index": "A", "chunker": "fixed", "size": 500, "overlap": 50, "use_filter": False},
    "B": {"index": "B", "chunker": "paragraph", "max_size": 800, "use_filter": False},
    "C": {"index": "B", "chunker": "paragraph", "max_size": 800, "use_filter": True},
}
INDEXES = {"A": STRATEGIES["A"], "B": STRATEGIES["B"]}

# Metadata fields that may be used as search filters (whitelist, values bound as SQL params)
FILTERABLE = ("chapter", "section", "page_type", "document_id")
TOP_K = 3
