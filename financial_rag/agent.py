"""Scoped research workflow with balanced retrieval and explicit offline evidence mode."""

import os
import re
import time

from .logging_config import event
from .pipeline import FlashReranker, assemble_context, generate_answer
from .registry import Registry
from .retrieval import Retriever

ABSTAIN = "I don't have enough evidence to answer this question."


def normalize_financial_query(question):
    """Expand common written variants before scope checks and lexical retrieval."""
    variants = {
        r"\bcash[\s-]*flows?\b": "cash flow",
        r"\bnetincome\b": "net income",
        r"\bEPS\b": "earnings per share",
        r"\bcapex\b": "capital expenditures",
        r"\bopex\b": "operating expenses",
    }
    for pattern, replacement in variants.items():
        question = re.sub(pattern, replacement, question, flags=re.I)
    return question


def numeric_check(answer, sources):
    """Conservative literal-number check, not a semantic/period correctness proof."""
    issues = []
    checked = 0
    valid = {s["citation_id"]: s for s in sources}
    for paragraph in answer.split("\n"):
        labels = re.findall(r"\[(S\d+)\]", paragraph)
        if any(label not in valid for label in labels):
            issues.append("Unknown citation")
            continue
        text = re.sub(r"\[S\d+\]", "", paragraph)
        # Markdown enumeration markers are formatting, not financial quantities.
        text = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", text)
        numbers = re.findall(r"(?<!\w)-?\d[\d,]*(?:\.\d+)?", text)
        if not numbers:
            continue
        evidence = " ".join(valid[label]["text"] for label in labels if label in valid).replace(
            ",", ""
        )
        for number in numbers:
            checked += 1
            if not re.search(
                r"(?<![\d.])" + re.escape(number.replace(",", "")) + r"(?!\d|\.\d)", evidence
            ):
                issues.append("A number does not occur in its cited passage")
    return {
        "passed": not issues,
        "checked_numbers": checked,
        "issues": list(dict.fromkeys(issues)),
        "scope": "Literal numeric support only; review units, fiscal columns and meaning in the original report.",
    }


class ResearchAgent:
    def __init__(self):
        self.registry = Registry()
        self.retriever = Retriever()
        self.reranker = None

    def answer(
        self,
        question,
        strategy="fixed",
        rerank=True,
        mode="hybrid",
        selector="active",
        context=None,
        offline=False,
    ):
        start = time.perf_counter()
        trace = []
        context = dict(context or {})
        original_question = question
        question = normalize_financial_query(question)
        if context.get("topic"):
            context["topic"] = normalize_financial_query(context["topic"])
        sources = []
        result = {
            "question": original_question,
            "strategy": strategy,
            "reranking": rerank,
            "sources": sources,
            "trace": trace,
            "context": context,
        }

        def finish(answer, status):
            result.update(
                answer=answer, answer_status=status, elapsed_seconds=time.perf_counter() - start
            )
            event(
                "agent.completed",
                status=status,
                strategy=strategy,
                rerank=rerank,
                mode=mode,
                offline=offline,
                sources=len(result["sources"]),
                elapsed_ms=round(result["elapsed_seconds"] * 1000, 2),
            )
            return result

        event("agent.started", strategy=strategy, mode=mode, rerank=rerank, offline=offline)
        active = {c["ticker"] for c in self.registry.companies(selector)}
        tickers = self.registry.detect(question) or context.get("tickers", [])
        if not tickers and selector not in ("active", "bundled") and selector in active:
            tickers = [selector]
        trace.append({"step": "Scope", "detail": ", ".join(tickers) or "Company needed"})
        if re.search(
            r"\b(predict|forecast stock|price target|should I buy|stock price tomorrow)\b",
            question,
            re.I,
        ):
            return finish(
                "This workspace answers filing questions. It cannot predict stock prices or recommend investments.",
                "refused",
            )
        if not tickers:
            years = re.findall(r"\b20\d{2}\b", question)
            result["context"] = {
                "tickers": [],
                "year": years[-1] if years else context.get("year"),
                "topic": question,
            }
            result["suggested_questions"] = [
                f"{company['ticker']}: {question}"
                for company in self.registry.companies(selector)[:4]
            ]
            return finish(
                "Which company would you like to research? Select one in Corpus, or include its name in your question.",
                "clarify",
            )
        if any(t not in active for t in tickers):
            return finish(
                "The selected corpus does not contain "
                + ", ".join(t for t in tickers if t not in active)
                + ". Add its filing or choose another corpus.",
                "refused",
            )
        if len(tickers) > 4:
            return finish("Please compare at most four companies in one question.", "clarify")
        domain = r"\b(revenue|sales|income|earnings|profit|risk|risks|assets|liabilities|cash|debt|margin|growth|business|filing|report|operating|capital|dividend|expense|expenses|performance|employees|cloud|results)\b"
        company_only = bool(tickers) and question.strip().lower().rstrip(".!?") in {
            name.lower().rstrip(".")
            for ticker in tickers
            for name in [ticker, (self.registry.company(ticker) or {}).get("name", "")]
            + (self.registry.company(ticker) or {}).get("aliases", [])
        }
        followup = bool(context.get("topic")) and (
            company_only
            or bool(
                re.search(
                    r"\b(and|it|its|them|their|same|last year|previous year|what about)\b",
                    question,
                    re.I,
                )
            )
        )
        result["context"] = {**context, "tickers": tickers}
        if not re.search(domain, question, re.I) and not followup:
            return finish(
                "Please ask a financial or filing question, such as revenue, risks, cash flow or business operations.",
                "clarify",
            )
        years = re.findall(r"\b20\d{2}\b", question)
        year = years[-1] if years else context.get("year")
        if not years and year and re.search(r"\b(last year|previous year)\b", question, re.I):
            year = str(int(year) - 1)
        topic = (
            context.get("topic", "")
            if followup and not re.search(domain, question, re.I)
            else question
        )
        result["context"] = {"tickers": tickers, "year": year, "topic": topic}
        resolved = (
            question
            + " Companies: "
            + ", ".join(tickers)
            + (f". Fiscal year: {year}" if year and not years else "")
        )
        if topic != question:
            resolved += " Topic: " + topic
        result["understood_as"] = resolved
        unavailable = [
            ticker
            for ticker in tickers
            if strategy not in self.registry.strategies(ticker, selector)
        ]
        if unavailable:
            supported = set.intersection(
                *(set(self.registry.strategies(ticker, selector)) for ticker in tickers)
            )
            result["available_strategies"] = [
                name for name in ("fixed", "semantic", "section") if name in supported
            ]
            trace.append(
                {
                    "step": "Index availability",
                    "detail": f"No {strategy} chunks for {', '.join(unavailable)}",
                }
            )
            alternatives = ", ".join(result["available_strategies"]) or "none yet"
            return finish(
                f"{strategy.capitalize()} chunking is not available for {', '.join(unavailable)} in this corpus. Available chunking strategies: {alternatives}. Newly added filings currently support fixed-size and section-aware retrieval. Choose one of those to search this filing.",
                "unsupported",
            )
        candidates = []
        backends = []
        for ticker in tickers:
            hits, backend = self.retriever.search(
                resolved,
                [ticker],
                strategy,
                mode=mode,
                offline=offline,
                selector=selector,
                limit=10,
            )
            if not hits:
                hits, backend = self.retriever.search(
                    question + " annual financial results risks",
                    [ticker],
                    strategy,
                    mode=mode,
                    offline=offline,
                    selector=selector,
                    limit=10,
                )
                trace.append(
                    {"step": "Rewrite", "detail": f"One bounded retrieval retry for {ticker}"}
                )
            if not hits:
                return finish(ABSTAIN, "abstained")
            terms = set(re.findall(domain, topic, re.I))
            if terms and not any(
                any(term.lower() in h["text"].lower() for term in terms) for h in hits
            ):
                trace.append(
                    {"step": "Grade", "detail": "No literal topic support in retrieved evidence"}
                )
                return finish(ABSTAIN, "abstained")
            if rerank:
                if self.reranker is None:
                    self.reranker = FlashReranker()
                hits = self.reranker(resolved, hits)
            candidates.extend(hits[: max(1, 6 // len(tickers))])
            backends.append(backend)
        trace.append(
            {
                "step": "Retrieve",
                "detail": f"{len(candidates)} passages; evidence reserved for each company",
            }
        )
        result["backend"] = "; ".join(sorted(set(backends)))
        evidence, sources = assemble_context(candidates)
        result["sources"] = sources
        if offline or not os.getenv("NEBIUS_API_KEY"):
            answer = "Evidence excerpts (not a synthesized answer):\n\n" + "\n\n".join(
                f"{s['text'][:650]} [{s['citation_id']}]" for s in sources
            )
            result["verification"] = {
                "passed": None,
                "scope": "Extractive excerpts; verify the full source table before using figures.",
            }
            trace.append({"step": "Extract", "detail": "No generation API used"})
            return finish(answer, "excerpts")
        from .workflow import guarded_generate

        generated = guarded_generate(resolved, evidence, sources, generate_answer, numeric_check)
        result["verification"] = generated["verification"]
        trace.extend(generated["trace"])
        answer = generated["answer"]
        return finish(answer, "abstained" if answer == ABSTAIN else "answered")
