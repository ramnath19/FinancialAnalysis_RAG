"""Six-way zero-key development retrieval benchmark; lexical vectors, not dense."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from financial_rag.pipeline import FlashReranker
from financial_rag.registry import ROOT, Registry
from financial_rag.retrieval import Retriever


def main():
    registry = Registry()
    retriever = Retriever(registry, online=False)
    reranker = FlashReranker()
    questions = json.loads((ROOT / "data/evaluation/development.json").read_text())
    rows = []
    trials = []
    for strategy in ("fixed", "section"):
        for mode, rerank in [("vector", False), ("hybrid", False), ("hybrid", True)]:
            ranks = []
            for q in questions:
                hits, backend = retriever.search(
                    q["question"], registry.detect(q["question"]), strategy, mode, "bundled", 10
                )
                if rerank:
                    hits = reranker(q["question"], hits)
                relevant = [
                    i
                    for i, h in enumerate(hits, 1)
                    if q["source_block_id"]
                    in [h["metadata"].get("source_block_id")]
                    + h["metadata"].get("source_block_ids", [])
                ]
                rank = min(relevant) if relevant else None
                ranks.append(rank)
                trials.append(
                    {
                        "id": q["id"],
                        "strategy": strategy,
                        "mode": mode,
                        "rerank": rerank,
                        "first_relevant_rank": rank,
                        "candidate_ids": [h["id"] for h in hits],
                    }
                )
            row = {
                "strategy": strategy,
                "mode": mode,
                "rerank": rerank,
                "queries": len(ranks),
                "hit_at_1": sum(r == 1 for r in ranks) / len(ranks),
                "hit_at_5": sum(r is not None and r <= 5 for r in ranks) / len(ranks),
                "mrr_at_10": sum(1 / r for r in ranks if r) / len(ranks),
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
    output = {
        "scope": "Development source-block retrieval only. TF-IDF lexical vectors; not Pinecone dense. No answer correctness claims. Shared source pages may contain several financial metrics.",
        "corpus": "bundled",
        "rows": rows,
        "trials": trials,
    }
    (ROOT / "reports/local-retrieval-comparison.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
