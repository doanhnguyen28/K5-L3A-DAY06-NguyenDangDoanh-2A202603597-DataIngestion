from collections import defaultdict
from typing import Any

from .ingestion import compact


def gold_evidence(question: dict[str, Any]) -> list[tuple[int, str]]:
    gold = question["gold_page"] if isinstance(question["gold_page"], list) else [question["gold_page"]]
    pairs = [(gold[0], question["evidence_quote"])]
    pairs += [(a["page"], a["quote"]) for a in question.get("alt_evidence") or []]
    return pairs


def is_hit(question: dict[str, Any], hit: dict[str, Any]) -> bool:
    if hit["document_id"] != question["gold_source_id"]:
        return False
    chunk = compact(hit["text"])
    return any(hit["page"] == page and compact(quote) in chunk for page, quote in gold_evidence(question))


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    gold_pages = {p for p, _ in gold_evidence(question)}
    hit_flags = [is_hit(question, h) for h in hits]
    page_flags = [h["document_id"] == question["gold_source_id"] and h["page"] in gold_pages for h in hits]
    flt = question.get("filter")
    result = {
        "hit_flags": hit_flags,
        "first_hit_rank": hit_flags.index(True) + 1 if any(hit_flags) else None,
        "hit_at_1": bool(hit_flags[:1] and hit_flags[0]),
        "hit_at_3": any(hit_flags[:3]),
        "gold_page_at_3": any(page_flags[:3]),
        "page_only_miss": any(page_flags[:3]) and not any(hit_flags[:3]),
        "filter_compliant": None,
    }
    if flt:
        result["filter_compliant"] = all(all(str(h.get(k)) == str(v) for k, v in flt.items()) for h in hits[:3])
    return result


def _frac(n: int, d: int) -> str:
    return f"{n}/{d}" if d else "N/A"


def summarize(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
    rows = []
    for (strategy, split), items in sorted(groups.items()):
        n = len(items)
        h1 = sum(t["eval"]["hit_at_1"] for t in items)
        h3 = sum(t["eval"]["hit_at_3"] for t in items)
        pg = sum(t["eval"]["gold_page_at_3"] for t in items)
        split_ev = sum(t["eval"]["page_only_miss"] for t in items)
        filtered = [t for t in items if t["filter"]]
        comp = sum(bool(t["eval"]["filter_compliant"]) for t in filtered)
        rows.append({
            "strategy": strategy, "split": split, "n": n,
            "hit_at_1": _frac(h1, n), "hit_at_1_pct": round(100 * h1 / n, 1),
            "evidence_hit_at_3": _frac(h3, n), "evidence_hit_at_3_pct": round(100 * h3 / n, 1),
            "gold_page_at_3": _frac(pg, n), "page_only_misses": split_ev,
            "filter_questions": len(filtered), "filter_compliant": _frac(comp, len(filtered)),
            "missed_ids": " ".join(t["question_id"] for t in items if not t["eval"]["hit_at_3"]),
        })
    return rows
