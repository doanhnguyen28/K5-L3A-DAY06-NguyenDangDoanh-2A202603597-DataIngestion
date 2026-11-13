import argparse
import csv
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from . import config
from .chunking import by_paragraph, fixed_size
from .ingestion import load_inventory, load_pdf
from .models import Chunk, DocumentPage


def _env() -> tuple[str, str]:
    load_dotenv(config.STARTER / ".env")
    url = os.getenv("DATABASE_URL", "")
    model = os.getenv("EMBEDDING_MODEL") or config.DEFAULT_EMBEDDING_MODEL
    return url, model


def build_chunks(pages: list[DocumentPage], spec: dict) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in pages:
        if spec["chunker"] == "fixed":
            chunks += fixed_size(page, spec["size"], spec["overlap"])
        elif spec["chunker"] == "paragraph":
            chunks += by_paragraph(page, spec["max_size"])
        else:
            raise ValueError(f"unknown chunker {spec['chunker']}")
    return chunks


def _length_stats(values: list[int]) -> dict:
    return {"min": min(values), "mean": round(statistics.mean(values), 1),
            "median": statistics.median(values), "max": max(values), "total": sum(values)}


def ingest(embedder=None, store=None) -> dict:
    from .embeddings import MyEmbedder
    from .store import PgVectorStore

    url, model_name = _env()
    t0 = time.perf_counter()
    inventory = load_inventory(config.INVENTORY)
    pages, log = load_pdf(config.PDF_PATH, config.DOCUMENT_ID, config.SOURCE, inventory)
    load_seconds = time.perf_counter() - t0
    if len(pages) < 30:
        raise SystemExit(f"Only {len(pages)} content pages loaded; need >= 30")

    t_model = time.perf_counter()
    embedder = embedder or MyEmbedder(model_name)
    model_load_seconds = time.perf_counter() - t_model
    store = store or PgVectorStore(url, embedder.dimensions)
    store.create_schema()

    config.RESULTS.mkdir(parents=True, exist_ok=True)
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "document_id": config.DOCUMENT_ID, "pages_ingested": len(pages),
        "page_load_seconds": round(load_seconds, 2),
        "embedding": {"provider": "local sentence-transformers", "model": embedder.model_name,
                      "library_version": embedder.library_version, "dimensions": embedder.dimensions,
                      "max_seq_length_tokens": embedder.max_seq_length, "normalized": True,
                      "query_document_handling": "identical encoding, no prefixes",
                      "device": "cpu", "model_load_seconds": round(model_load_seconds, 2)},
        "vector_store": {"backend": "PostgreSQL + pgvector", "table": "chunks",
                         "metric": "cosine distance (<=>)", "search": "exact (no ANN index)"},
        "python": platform.python_version(), "cost_usd": 0.0, "indexes": {},
    }
    for index, spec in config.INDEXES.items():
        t1 = time.perf_counter()
        chunks = build_chunks(pages, spec)
        chunk_seconds = time.perf_counter() - t1

        existing = store.existing_hashes(index, config.DOCUMENT_ID)
        todo = [i for i, c in enumerate(chunks)
                if existing.get(c.chunk_id) != (c.metadata["content_hash"], embedder.model_name)]
        t2 = time.perf_counter()
        new_vectors = embedder.embed_documents([chunks[i].text for i in todo])
        embed_seconds = time.perf_counter() - t2
        vectors: list = [None] * len(chunks)
        for i, v in zip(todo, new_vectors):
            vectors[i] = v

        t3 = time.perf_counter()
        db = store.upsert(index, chunks, vectors, embedder.model_name, config.DOCUMENT_ID)
        db_seconds = time.perf_counter() - t3

        tokens = [embedder.count_tokens(c.text) for c in chunks]
        report["indexes"][index] = {
            "params": spec, "used_by_strategies": [s for s, v in config.STRATEGIES.items() if v["index"] == index],
            "chunk_count": len(chunks), "chars": _length_stats([len(c.text) for c in chunks]),
            "tokens": _length_stats(tokens),
            "chunks_over_max_seq_length": sum(t > embedder.max_seq_length for t in tokens),
            "embedded_this_run": len(todo), **db,
            "seconds": {"chunk": round(chunk_seconds, 2), "embed": round(embed_seconds, 2),
                        "db": round(db_seconds, 2)},
        }
        with (config.RESULTS / f"chunks_{index}.jsonl").open("w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps({"chunk_id": c.chunk_id, "page": c.page, **c.metadata, "text": c.text},
                                   ensure_ascii=False) + "\n")
        print(f"[{index}] {len(chunks)} chunks | embedded {len(todo)} in {embed_seconds:.1f}s | db {db}")

    with (config.RESULTS / "ingest_log.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["page", "level", "event", "detail"])
        writer.writeheader()
        writer.writerows(log)
    (config.RESULTS / "ingest_stats.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {config.RESULTS / 'ingest_stats.json'}")
    return report


def check_reingest() -> None:
    from .embeddings import MyEmbedder
    from .store import PgVectorStore

    url, model_name = _env()
    embedder = MyEmbedder(model_name)
    store = PgVectorStore(url, embedder.dimensions)
    store.create_schema()
    before = store.counts()
    report = ingest(embedder, store)
    after = store.counts()
    ok = before == after and all(v["duplicate_positions"] == 0 and v["rows"] == v["distinct_ids"]
                                 for v in after.values())
    lines = [f"Re-ingest check at {report['run_at']}",
             f"before: {json.dumps(before)}", f"after:  {json.dumps(after)}"]
    for index, s in report["indexes"].items():
        lines.append(f"[{index}] chunk_count={s['chunk_count']} embedded_this_run={s['embedded_this_run']} "
                     f"written={s['written']} unchanged={s['unchanged']} deleted={s['deleted']}")
    lines.append("RESULT: " + ("OK - same row counts, no duplicate chunks, nothing re-embedded"
                               if ok and all(s["embedded_this_run"] == 0 for s in report["indexes"].values())
                               else "CHECK - see numbers above"))
    text = "\n".join(lines)
    (config.RESULTS / "reingest_check.txt").write_text(text + "\n", encoding="utf-8")
    print(text)


def search(query: str, strategy: str, chapter: str | None) -> None:
    from .embeddings import MyEmbedder
    from .store import PgVectorStore

    url, model_name = _env()
    spec = config.STRATEGIES[strategy]
    embedder = MyEmbedder(model_name)
    store = PgVectorStore(url, embedder.dimensions)
    filters = {"chapter": chapter} if (chapter and spec["use_filter"]) else None
    if chapter and not spec["use_filter"]:
        print(f"(strategy {strategy} does not use filters; --chapter ignored)")
    for rank, hit in enumerate(store.search(spec["index"], embedder.embed_query(query), config.TOP_K, filters), 1):
        print(f"#{rank} score={hit['score']:.3f} page={hit['page']} ch={hit['chapter']} "
              f"sec={hit['section']} id={hit['chunk_id']}\n    {hit['text'][:160]!r}")


def evaluate(split: str, questions: str | None, out: str | None) -> None:
    from pathlib import Path

    from .embeddings import MyEmbedder
    from .experiments import run_benchmark
    from .store import PgVectorStore

    url, model_name = _env()
    embedder = MyEmbedder(model_name)
    store = PgVectorStore(url, embedder.dimensions)
    run_benchmark(embedder, store, split, Path(questions) if questions else config.QUESTIONS,
                  Path(out) if out else config.RESULTS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 06 data ingestion pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest")
    sub.add_parser("check-reingest")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("-s", "--strategy", choices=list(config.STRATEGIES), default="B")
    p.add_argument("--chapter")
    e = sub.add_parser("evaluate", help="run benchmark for A/B/C and save traces + metrics")
    e.add_argument("--split", choices=["dev", "test", "all"], required=True)
    e.add_argument("--questions", help="override benchmark file (default: ../benchmark/questions.jsonl)")
    e.add_argument("--out", help="override output folder (default: results/)")
    a = sub.add_parser("export-audit", help="write blank manual-labeling CSV sheets")
    a.add_argument("--out")
    s = sub.add_parser("summarize-audit", help="aggregate filled-in manual labels")
    s.add_argument("--out")
    args = parser.parse_args()
    if args.cmd == "ingest":
        ingest()
    elif args.cmd == "check-reingest":
        check_reingest()
    elif args.cmd == "search":
        search(args.query, args.strategy, args.chapter)
    elif args.cmd == "evaluate":
        evaluate(args.split, args.questions, args.out)
    else:
        from pathlib import Path

        from .experiments import export_audit, summarize_audit
        out = Path(args.out) if args.out else config.RESULTS
        (export_audit if args.cmd == "export-audit" else summarize_audit)(out)


if __name__ == "__main__":
    sys.exit(main())
