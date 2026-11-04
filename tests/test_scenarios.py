import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from financial_rag import ingestion, market
from financial_rag.agent import ResearchAgent, numeric_check
from financial_rag.limits import Limits
from financial_rag.registry import Registry
from financial_rag.retrieval import LocalIndex, rrf
from financial_rag.section_chunk import section_chunks


class Scenarios(unittest.TestCase):
    def test_scope_and_memory(self):
        agent = ResearchAgent()
        self.assertEqual(agent.answer("What is net income?")["answer_status"], "clarify")
        self.assertEqual(
            agent.answer("Tesla revenue?", selector="bundled")["answer_status"], "refused"
        )
        self.assertEqual(
            agent.answer("Predict Apple stock price tomorrow")["answer_status"], "refused"
        )
        source = {
            "id": "one",
            "text": "Revenue in 2025 was 100.",
            "metadata": {"company": "Apple", "ticker": "AAPL"},
        }
        with patch.object(agent.retriever, "search", return_value=([source], "mock")):
            r = agent.answer(
                "And revenue?",
                context={"tickers": ["AAPL"], "year": "2025"},
                rerank=False,
                offline=True,
            )
        self.assertEqual(r["answer_status"], "excerpts")
        self.assertEqual(r["context"]["year"], "2025")

    def test_balanced(self):
        agent = ResearchAgent()

        def search(query, tickers, *a, **k):
            t = tickers[0]
            return ([{"id": t, "text": t + " revenue 2025", "metadata": {"ticker": t}}], "mock")

        with patch.object(agent.retriever, "search", side_effect=search):
            r = agent.answer(
                "Compare Apple and Microsoft revenue in 2025", rerank=False, offline=True
            )
        self.assertEqual({s["metadata"]["ticker"] for s in r["sources"]}, {"AAPL", "MSFT"})

    def test_selected_company_corpus_resolves_companyless_question(self):
        agent = ResearchAgent()
        passage = {
            "id": "one",
            "text": "Apple revenue in 2025.",
            "metadata": {"company": "Apple", "ticker": "AAPL"},
        }
        with patch.object(agent.retriever, "search", return_value=([passage], "mock")) as search:
            result = agent.answer(
                "What was revenue in 2025?", selector="AAPL", rerank=False, offline=True
            )
        self.assertEqual(result["answer_status"], "excerpts")
        self.assertEqual(result["context"]["tickers"], ["AAPL"])
        self.assertEqual(search.call_args.args[1], ["AAPL"])
        self.assertTrue(result["answer"].strip())

    def test_company_reply_completes_pending_question(self):
        agent = ResearchAgent()
        first = agent.answer("What was revenue in 2025?", rerank=False, offline=True)
        self.assertEqual(first["answer_status"], "clarify")
        self.assertTrue(first["suggested_questions"])
        passage = {"id": "one", "text": "Apple revenue in 2025.", "metadata": {"ticker": "AAPL"}}
        with patch.object(agent.retriever, "search", return_value=([passage], "mock")):
            second = agent.answer("Apple", context=first["context"], rerank=False, offline=True)
        self.assertEqual(second["answer_status"], "excerpts")
        self.assertEqual(second["context"]["year"], "2025")
        self.assertIn("What was revenue in 2025?", second["understood_as"])

    def test_financial_wording_variants_reach_retrieval(self):
        agent = ResearchAgent()
        passage = {
            "id": "cash",
            "text": "Cash flow from operating activities was reported in 2025. Earnings per share and capital expenditures.",
            "metadata": {"company": "Apple", "ticker": "AAPL"},
        }
        for phrase, expected in [
            ("cashflow", "cash flow"),
            ("cash-flow", "cash flow"),
            ("cashflows", "cash flow"),
            ("EPS", "earnings per share"),
            ("capex", "capital expenditures"),
        ]:
            with (
                self.subTest(phrase=phrase),
                patch.object(agent.retriever, "search", return_value=([passage], "mock")) as search,
            ):
                result = agent.answer(
                    f"What is the {phrase} of AAPL for 2025",
                    selector="AAPL",
                    rerank=False,
                    offline=True,
                )
                self.assertEqual(result["answer_status"], "excerpts")
                search.assert_called_once()
                self.assertIn(expected, result["understood_as"])
                self.assertIn(phrase, result["question"])

    def test_missing_strategy_explains_index_availability(self):
        agent = ResearchAgent()
        with (
            patch.object(agent.registry, "strategies", return_value=["fixed", "section"]),
            patch.object(agent.retriever, "search") as search,
        ):
            result = agent.answer(
                "Operating cash flow for Apple", strategy="semantic", selector="AAPL"
            )
        search.assert_not_called()
        self.assertEqual(result["answer_status"], "unsupported")
        self.assertEqual(result["available_strategies"], ["fixed", "section"])
        self.assertIn("not available", result["answer"])
        self.assertEqual(result["context"]["tickers"], ["AAPL"])

    def test_numeric_citation_scope(self):
        sources = [
            {"citation_id": "S1", "text": "2025 revenue 100 million"},
            {"citation_id": "S2", "text": "200 million"},
        ]
        self.assertTrue(numeric_check("2025 revenue 100 million [S1]", sources)["passed"])
        self.assertFalse(numeric_check("200 million [S1]", sources)["passed"])
        self.assertFalse(numeric_check("100 million [S9]", sources)["passed"])
        self.assertFalse(numeric_check("100 million", sources)["passed"])

    def test_numeric_list_marker_is_not_a_financial_amount(self):
        sources = [
            {
                "citation_id": "S1",
                "text": "Net cash provided by operating activities was 14,747 million in 2025.",
            }
        ]
        result = numeric_check("1. Operating cash flow was 14,747 million in 2025 [S1].", sources)
        self.assertTrue(result["passed"])
        self.assertEqual(result["checked_numbers"], 2)
        self.assertFalse(
            numeric_check("1. Operating cash flow was 999 million [S1].", sources)["passed"]
        )

    def test_sections(self):
        block = {
            "document_id": "d",
            "block_id": "b",
            "kind": "text",
            "location": {"pdf_page": 1},
            "text": "Item 1. Business\n"
            + ("Business. " * 40)
            + "\nItem 1A. Risk Factors\n"
            + ("Risk. " * 40),
        }
        chunks = section_chunks([block], 200)
        self.assertEqual({c["location"]["section"] for c in chunks}, {"Item 1", "Item 1A"})
        self.assertTrue(all(len(c["text"]) <= 200 for c in chunks))
        self.assertTrue(all(not ("Business" in c["text"] and "Risk" in c["text"]) for c in chunks))

    def test_rrf_and_local_scope(self):
        self.assertEqual(rrf([[{"id": "a"}, {"id": "b"}], [{"id": "b"}]])[0]["id"], "b")
        chunks = [
            {
                "chunk_id": t,
                "ticker": t,
                "document_id": t,
                "location": {},
                "text": "Revenue growth annual filing",
            }
            for t in ["AAPL", "MSFT"]
        ]
        index = LocalIndex(chunks)
        self.assertEqual([h["id"] for h in index.search("revenue", ["MSFT"], {"MSFT"})], ["MSFT"])

    def test_registry_persistence(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / "data"
            data.mkdir()
            (data / "manifest.json").write_text("[]")
            r = Registry(root)
            r.register(
                {
                    "ticker": "TSLA",
                    "documents": [{"ticker": "TSLA", "company": "Tesla", "document_id": "t"}],
                }
            )
            self.assertEqual(Registry(root).detect("Tesla revenue"), ["TSLA"])
            self.assertEqual(r.documents("bundled"), [])

    def test_limits(self):
        limits = Limits()
        self.assertTrue(all(limits.allow("a", now=1) for _ in range(30)))
        self.assertFalse(limits.allow("a", now=1))
        self.assertTrue(limits.allow("b", now=1))
        self.assertTrue(limits.allow("a", now=3602))

    def test_market_failure_and_cache(self):
        market.CACHE.clear()
        with patch.object(market, "download", side_effect=OSError("offline")) as fetch:
            self.assertFalse(market.history("AAPL")["available"])
            self.assertEqual(fetch.call_count, 2)
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1700000000],
                        "indicators": {"quote": [{"close": [100]}]},
                        "meta": {"currency": "USD"},
                    }
                ]
            }
        }
        with patch.object(market, "download", return_value=json.dumps(payload)) as fetch:
            self.assertTrue(market.history("AAPL")["available"])
            market.history("AAPL")
            self.assertEqual(fetch.call_count, 1)

    def test_ingestion_mock_and_refresh(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "data").mkdir()
            (root / "data/manifest.json").write_text("[]")
            registry = Registry(root)
            mapping = {"0": {"ticker": "TSLA", "cik_str": 1318605, "title": "Tesla"}}
            submissions = {
                "filings": {
                    "recent": {
                        "form": ["10-K"],
                        "accessionNumber": ["0001-26-01"],
                        "primaryDocument": ["a.htm"],
                        "reportDate": ["2025-12-31"],
                    }
                }
            }

            def fetch(url):
                if "company_tickers" in url:
                    return json.dumps(mapping).encode()
                if "submissions" in url:
                    return json.dumps(submissions).encode()
                if "companyfacts" in url:
                    return b'{"facts":{}}'
                return b"<html><h1>Item 1. Business</h1><p>Tesla builds cars.</p><h1>Item 1A. Risks</h1><p>Supply risks.</p></html>"

            ingestion.JOBS["test"] = {"status": "running"}
            with (
                patch.object(ingestion, "ROOT", root),
                patch.object(ingestion, "Registry", return_value=registry),
                patch.object(ingestion, "fetch", side_effect=fetch),
            ):
                ingestion.run("test", "TSLA")
                self.assertEqual(ingestion.JOBS["test"]["status"], "complete")
                self.assertTrue((root / "data/session/TSLA/fixed.jsonl").exists())
                self.assertEqual(registry.detect("Tesla revenue"), ["TSLA"])
                ingestion.run("test", "TSLA")
                self.assertEqual(ingestion.JOBS["test"]["stage"], "Already current")


class WorkflowTests(unittest.TestCase):
    def test_bounded_regeneration(self):
        from financial_rag.workflow import guarded_generate

        calls = []

        def generate(*args):
            calls.append(args)
            return "999 [S1]"

        result = guarded_generate(
            "revenue", "100", [{"citation_id": "S1", "text": "100"}], generate, numeric_check
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["answer"], "I don't have enough evidence to answer this question.")

    def test_graph_accepts_supported_number(self):
        from financial_rag.workflow import guarded_generate

        result = guarded_generate(
            "revenue",
            "100",
            [{"citation_id": "S1", "text": "100"}],
            lambda *a: "100 [S1]",
            numeric_check,
        )
        self.assertEqual(result["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
