"""Validated UI requests and read-only workspace views, independent of HTTP."""

import json
import os
import re
import threading
from dataclasses import dataclass

from .registry import Registry

STRATEGIES = ("fixed", "semantic", "section")
TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")


@dataclass(frozen=True)
class AskRequest:
    question: str
    strategy: str
    rerank: bool
    mode: str
    selector: str
    context: dict
    offline: bool

    @classmethod
    def parse(cls, body):
        question = body.get("question", "")
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise ValueError("Enter a question of 1–2000 characters.")
        strategy, mode = body.get("strategy", "fixed"), body.get("mode", "hybrid")
        if strategy not in STRATEGIES or mode not in ("vector", "hybrid"):
            raise ValueError("Choose a supported chunking and retrieval method.")
        rerank, offline = body.get("rerank", True), body.get("offline", False)
        if type(rerank) is not bool or type(offline) is not bool:
            raise ValueError("Reranking and local mode must be boolean settings.")
        selector = body.get("selector", "active")
        if not isinstance(selector, str) or (
            selector not in ("active", "bundled") and not TICKER.fullmatch(selector)
        ):
            raise ValueError("Choose a valid document corpus.")
        context = body.get("context", {})
        if not isinstance(context, dict):
            raise ValueError("Conversation context must be an object.")
        tickers, year, topic = (
            context.get("tickers", []),
            context.get("year"),
            context.get("topic", ""),
        )
        if (
            not isinstance(tickers, list)
            or len(tickers) > 4
            or any(not isinstance(t, str) or not TICKER.fullmatch(t) for t in tickers)
        ):
            raise ValueError("Conversation context supports up to four ticker symbols.")
        if year is not None and (not isinstance(year, str) or not re.fullmatch(r"20\d{2}", year)):
            raise ValueError("Conversation year must be a four-digit year.")
        if not isinstance(topic, str) or len(topic) > 2000:
            raise ValueError("Conversation topic is too long or invalid.")
        return cls(
            question.strip(),
            strategy,
            rerank,
            mode,
            selector,
            {"tickers": tickers, "year": year, "topic": topic},
            offline,
        )


class Workspace:
    def __init__(self, registry=None):
        self.registry = registry or Registry()
        self._chunk_cache = {}
        self._lock = threading.Lock()

    def status(self):
        companies = self.registry.companies()
        for company in companies:
            company["strategies"] = self.registry.strategies(company["ticker"])
        return {
            "configured": bool(os.getenv("NEBIUS_API_KEY")),
            "services": {
                "generation": bool(os.getenv("NEBIUS_API_KEY")),
                "dense_retrieval": all(
                    os.getenv(k) for k in ("PINECONE_API_KEY", "PINECONE_INDEX_HOST")
                ),
                "sec": bool(os.getenv("SEC_USER_AGENT")),
            },
            "companies": companies,
            "documents": sum(len(c["documents"]) for c in companies),
            "sec_configured": bool(os.getenv("SEC_USER_AGENT")),
        }

    def chunks(self, strategy):
        if strategy not in STRATEGIES:
            raise ValueError("Choose a valid chunk strategy.")
        path = self.registry.root / f"data/chunks/reference/{strategy}.jsonl"
        signature = (path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else None
        with self._lock:
            cached = self._chunk_cache.get(strategy)
            if cached and cached[0] == signature:
                return cached[1]
            count = total = maximum = 0
            samples = []
            if path.exists():
                with path.open() as stream:
                    for line in stream:
                        chunk = json.loads(line)
                        size = len(chunk["text"])
                        count += 1
                        total += size
                        maximum = max(maximum, size)
                        if len(samples) < 3:
                            samples.append(chunk)
            result = {
                "strategy": strategy,
                "count": count,
                "mean_characters": round(total / count) if count else 0,
                "max_characters": maximum,
                "samples": samples,
            }
            self._chunk_cache[strategy] = (signature, result)
            return result

    def evaluation(self):
        report = self.registry.root / "reports/final-comparison.md"
        local = report.parent / "local-retrieval-comparison.json"
        return {
            "report": report.read_text() if report.exists() else "No completed benchmark report.",
            "local_retrieval": json.loads(local.read_text()) if local.exists() else None,
        }
