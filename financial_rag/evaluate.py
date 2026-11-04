"""Run and score all four chunking/reranking configurations."""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from .config import load_env


def numeric_reference_present(answer, values):
    # Ignore display commas/trailing zeros, but do not infer units or scales.
    from decimal import Decimal

    tokens = {
        Decimal(token.replace(",", "")) for token in re.findall(r"-?\d[\d,]*(?:\.\d+)?", answer)
    }
    return all(Decimal(value.replace(",", "")) in tokens for value in values)


def summarize(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["configuration"]].append(row)
    report = []
    for name, items in grouped.items():
        ok = [r for r in items if "error" not in r]
        report.append(
            {
                "configuration": name,
                "questions": len(items),
                "completed": len(ok),
                "abstentions": sum(
                    r.get("answer_status") == "abstained"
                    or r.get("answer") == "I don't have enough evidence to answer this question."
                    for r in ok
                ),
                "numeric_reference_presence": sum(r["numeric_reference_presence"] for r in ok)
                / len(ok)
                if ok
                else None,
                "reference_number_in_context": sum(
                    r.get("reference_number_in_context", False) for r in ok
                )
                / len(ok)
                if ok
                else None,
                "mean_seconds": sum(r["elapsed_seconds"] for r in ok) / len(ok) if ok else None,
            }
        )
    return report


def score_ragas(rows, output):
    import os

    from langchain_openai import ChatOpenAI
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
    )
    from ragas.run_config import RunConfig

    provider = os.getenv("RAGAS_JUDGE_PROVIDER", "openai")
    if provider == "nebius":
        judge_model = ChatOpenAI(
            model=os.getenv(
                "RAGAS_JUDGE_MODEL", os.getenv("NEBIUS_MODEL", "google/gemma-3-27b-it")
            ),
            api_key=os.environ["NEBIUS_API_KEY"],
            base_url=os.environ["NEBIUS_BASE_URL"],
            temperature=0,
        )
    else:
        judge_model = ChatOpenAI(model=os.getenv("RAGAS_JUDGE_MODEL", "gpt-4o-mini"), temperature=0)
    judge = LangchainLLMWrapper(judge_model)
    scores = []
    for name in sorted({r["configuration"] for r in rows}):
        group = [r for r in rows if r["configuration"] == name and "error" not in r]
        if not group:
            continue
        dataset = EvaluationDataset(
            samples=[
                SingleTurnSample(
                    user_input=r["question"],
                    response=r["answer"],
                    retrieved_contexts=[s["context_text"] for s in r["sources"]],
                    reference=r["reference"],
                )
                for r in group
            ]
        )
        result = evaluate(
            dataset,
            metrics=[Faithfulness(), LLMContextPrecisionWithReference(), LLMContextRecall()],
            llm=judge,
            raise_exceptions=True,
            show_progress=True,
            run_config=RunConfig(max_workers=4, timeout=180, max_retries=5),
        )
        frame = result.to_pandas()
        frame.to_json(output / (name + "-ragas.json"), orient="records", indent=2)
        columns = ["faithfulness", "llm_context_precision_with_reference", "context_recall"]
        scores.append(
            {
                "configuration": name,
                "scores": {
                    column: float(frame[column].mean()) if frame[column].notna().any() else None
                    for column in columns
                    if column in frame
                },
                "scored_samples": {
                    column: int(frame[column].notna().sum())
                    for column in columns
                    if column in frame
                },
            }
        )
    (output / "ragas-summary.json").write_text(json.dumps(scores, indent=2) + "\n")


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/evaluation/development.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/evaluation"))
    parser.add_argument("--ragas", action="store_true")
    parser.add_argument("--score-existing", action="store_true")
    parser.add_argument(
        "--strategies", nargs="+", choices=["fixed", "semantic"], default=["fixed", "semantic"]
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "runs.jsonl"
    if args.score_existing:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
    else:
        from .pipeline import FinancialRAG

        rag = FinancialRAG()
        rows = (
            [json.loads(line) for line in path.read_text().splitlines()]
            if args.resume and path.exists()
            else []
        )
        completed = {(r["query_id"], r["configuration"]) for r in rows if "error" not in r}
        rows = [r for r in rows if "error" not in r]
        if args.resume:
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        with path.open("a" if args.resume else "w") as f:
            dataset = json.loads(args.dataset.read_text())
            for item in dataset[: args.limit] if args.limit else dataset:
                for strategy in args.strategies:
                    for rerank in [False, True]:
                        name = f"{strategy}-" + ("rerank" if rerank else "direct")
                        if (item["id"], name) in completed:
                            continue
                        try:
                            result = rag.answer(item["question"], strategy, rerank)
                            result.update(
                                configuration=name,
                                query_id=item["id"],
                                reference=item["reference"],
                                numeric_reference_presence=numeric_reference_present(
                                    result["answer"], item["expected_numbers"]
                                ),
                                reference_number_in_context=numeric_reference_present(
                                    " ".join(s["context_text"] for s in result["sources"]),
                                    item["expected_numbers"],
                                ),
                            )
                        except Exception as exc:
                            # Avoid writing service errors that could contain request headers.
                            result = {
                                "configuration": name,
                                "query_id": item["id"],
                                "error": type(exc).__name__,
                            }
                        rows.append(result)
                        f.write(json.dumps(result, ensure_ascii=False) + "\n")
                        f.flush()
                        print(
                            item["id"],
                            name,
                            "error" if "error" in result else "complete",
                            flush=True,
                        )
    (args.output / "comparison.json").write_text(json.dumps(summarize(rows), indent=2) + "\n")
    if args.ragas:
        score_ragas(rows, args.output)
    if any("error" in r for r in rows):
        raise SystemExit("Some runs failed; see runs.jsonl. No complete comparison can be claimed.")


if __name__ == "__main__":
    main()
