import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .evaluation import evaluate_query, gold_evidence, summarize
from .ingestion import compact, load_inventory, load_pdf

TRACE_FIELDS = ("chunk_id", "document_id", "source", "page", "chapter", "section",
                "section_title", "page_type", "char_start", "char_end")


def load_questions(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: opens cleanly in Excel
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_benchmark(embedder, store, split: str, questions_path: Path, out: Path) -> list[dict]:
    questions = [q for q in load_questions(questions_path) if split == "all" or q["split"] == split]
    if not questions:
        raise SystemExit(f"no questions for split={split}")
    out.mkdir(parents=True, exist_ok=True)
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    query_vectors = {}
    t0 = time.perf_counter()
    for q in questions:                      # same query vector for every strategy
        query_vectors[q["id"]] = embedder.embed_query(q["question"])
    embed_seconds = time.perf_counter() - t0

    traces = []
    for strategy, spec in config.STRATEGIES.items():
        for q in questions:
            filters = q["filter"] if (spec["use_filter"] and q.get("filter")) else None
            t1 = time.perf_counter()
            hits = store.search(spec["index"], query_vectors[q["id"]], config.TOP_K, filters)
            latency_ms = (time.perf_counter() - t1) * 1000
            ev = evaluate_query(q, hits)
            traces.append({
                "run_at": run_at, "strategy": strategy, "index": spec["index"],
                "question_id": q["id"], "split": q["split"], "type": q.get("type"),
                "question": q["question"], "filter": q.get("filter"), "filter_applied": filters,
                "gold_source_id": q["gold_source_id"], "gold_page": q["gold_page"],
                "evidence_quote": q["evidence_quote"], "alt_evidence": q.get("alt_evidence") or [],
                "expected_answer": q["expected_answer"],
                "top_k": [{"rank": r, "score": round(float(h["score"]), 4),
                           **{k: h[k] for k in TRACE_FIELDS}, "text": h["text"],
                           "is_hit": ev["hit_flags"][r - 1]}
                          for r, h in enumerate(hits, start=1)],
                "eval": {k: v for k, v in ev.items() if k != "hit_flags"},
                "search_latency_ms": round(latency_ms, 2),
            })

    tag = split
    with (out / f"traces_{tag}.jsonl").open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    metrics = summarize(traces)
    _write_csv(out / f"metrics_{tag}.csv", metrics)
    (out / f"run_{tag}.json").write_text(json.dumps({
        "run_at": run_at, "split": split, "questions": len(questions),
        "embedding_model": embedder.model_name, "dimensions": embedder.dimensions,
        "query_embed_seconds": round(embed_seconds, 2), "top_k": config.TOP_K,
        "strategies": config.STRATEGIES, "cost_usd": 0.0,
    }, indent=2), encoding="utf-8")

    print(f"\n{'strategy':8} {'split':5} {'Hit@1':>7} {'EvHit@3':>8} {'page@3':>7} {'filter':>7}  missed@3")
    for m in metrics:
        print(f"{m['strategy']:8} {m['split']:5} {m['hit_at_1']:>7} {m['evidence_hit_at_3']:>8} "
              f"{m['gold_page_at_3']:>7} {m['filter_compliant']:>7}  {m['missed_ids']}")
    print(f"\nWrote traces_{tag}.jsonl, metrics_{tag}.csv, run_{tag}.json in {out}")
    return traces


def coherence_positions(pages, n: int = 10) -> list[tuple[int, int]]:
    pages = sorted(pages, key=lambda p: p.page)
    picks = [pages[round(i * (len(pages) - 1) / (n - 1))] for i in range(n)]
    return [(p.page, len(p.text) // 2) for p in picks]


def export_audit(out: Path) -> None:
    inventory = load_inventory(config.INVENTORY)
    pages, _ = load_pdf(config.PDF_PATH, config.DOCUMENT_ID, config.SOURCE, inventory)
    page_text = {p.page: p.text for p in pages}

    # 1) Coherence: same 10 source positions for every strategy (C uses B's chunks).
    chunks = {idx: [json.loads(l) for l in (out / f"chunks_{idx}.jsonl").read_text(encoding="utf-8").splitlines()]
              for idx in config.INDEXES}
    rows = []
    for pos_id, (page, offset) in enumerate(coherence_positions(pages), start=1):
        for strategy, spec in config.STRATEGIES.items():
            covering = [c for c in chunks[spec["index"]] if c["page"] == page and c["char_start"] <= offset < c["char_end"]]
            c = covering[0] if covering else None
            rows.append({
                "position_id": pos_id, "page": page, "char_offset": offset, "strategy": strategy,
                "chunk_id": c["chunk_id"] if c else "NOT COVERED",
                "note": "same chunk as B (C only adds a filter)" if strategy == "C" else "",
                "chunk_text": c["text"] if c else "",
                "score_0_2": "", "reason": "",
            })
    _write_csv(out / "audit_coherence.csv", rows)

    # 2) + 3) Metadata and grounding on the TEST split (requires traces_test.jsonl).
    test_path = out / "traces_test.jsonl"
    if not test_path.exists():
        print("audit_coherence.csv written. Run `evaluate --split test` first for metadata/grounding sheets.")
        return
    traces = [json.loads(l) for l in test_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    meta_rows, ground_rows = [], []
    for t in traces:
        for h in t["top_k"]:
            inv = inventory.get(h["page"], {})
            meta_rows.append({
                "question_id": t["question_id"], "strategy": t["strategy"], "rank": h["rank"],
                "chunk_id": h["chunk_id"], "source": h["source"], "page": h["page"],
                "chapter": h["chapter"], "section": h["section"],
                "filter": json.dumps(t["filter"]) if t["filter"] else "",
                "auto_text_found_on_page": compact(h["text"]) in compact(page_text.get(h["page"], "")),
                "auto_chapter_matches_inventory": str(inv.get("chapter")) == str(h["chapter"]),
                "chunk_excerpt": h["text"][:200],
                "source_ok": "", "page_ok": "", "chapter_ok": "", "all_correct": "", "error_note": "",
            })
        ground_rows.append({
            "question_id": t["question_id"], "strategy": t["strategy"], "question": t["question"],
            "filter_applied": json.dumps(t["filter_applied"]) if t["filter_applied"] else "",
            "expected_answer": t["expected_answer"], "gold_page": json.dumps(t["gold_page"]),
            "evidence_quote": t["evidence_quote"],
            "auto_evidence_hit_at_3": t["eval"]["hit_at_3"],
            **{f"top{h['rank']}": f"[p{h['page']} {h['chunk_id']}] {h['text']}" for h in t["top_k"]},
            "grounding_0_2": "", "reason": "",
        })
    _write_csv(out / "audit_metadata.csv", meta_rows)
    _write_csv(out / "audit_grounding.csv", ground_rows)
    print(f"Wrote audit_coherence.csv, audit_metadata.csv, audit_grounding.csv in {out}")


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def summarize_audit(out: Path) -> None:
    lines = []
    coh = out / "audit_coherence.csv"
    if coh.exists():
        rows = _read_csv(coh)
        lines.append("Coherence (mean /2, n positions):")
        for s in config.STRATEGIES:
            vals = [int(r["score_0_2"]) for r in rows if r["strategy"] == s and r["score_0_2"].strip()]
            total = sum(r["strategy"] == s for r in rows)
            lines.append(f"  {s}: " + (f"{sum(vals) / len(vals):.2f} (n={len(vals)}/{total})" if vals else f"not labeled (0/{total})"))
    meta = out / "audit_metadata.csv"
    if meta.exists():
        rows = _read_csv(meta)
        lines.append("Metadata complete & correct (records):")
        for s in config.STRATEGIES:
            mine = [r for r in rows if r["strategy"] == s]
            labeled = [r for r in mine if r["all_correct"].strip()]
            ok = sum(r["all_correct"].strip().lower() in {"1", "yes", "y", "true", "x"} for r in labeled)
            lines.append(f"  {s}: {ok}/{len(labeled)} labeled ({len(mine)} records)")
    gr = out / "audit_grounding.csv"
    if gr.exists():
        rows = _read_csv(gr)
        lines.append("Grounding (count of 0/1/2, mean /2):")
        for s in config.STRATEGIES:
            vals = [int(r["grounding_0_2"]) for r in rows if r["strategy"] == s and r["grounding_0_2"].strip()]
            if vals:
                lines.append(f"  {s}: 0={vals.count(0)} 1={vals.count(1)} 2={vals.count(2)} "
                             f"mean={sum(vals) / len(vals):.2f} (n={len(vals)})")
            else:
                lines.append(f"  {s}: not labeled")
    text = "\n".join(lines) or "No audit files found."
    (out / "audit_summary.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
