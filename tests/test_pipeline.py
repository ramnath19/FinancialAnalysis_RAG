import unittest
from unittest.mock import patch

from financial_rag.evaluate import numeric_reference_present, summarize
from financial_rag.pipeline import FinancialRAG, generate_answer, normalize_hits
from financial_rag.reference_chunk import split_block


class PipelineTests(unittest.TestCase):
    def test_document_hit_fields(self):
        hits = normalize_hits(
            {"matches": [{"_id": "a", "_score": 0.9, "chunk_text": "evidence", "company": "Demo"}]}
        )
        self.assertEqual(hits[0]["id"], "a")
        self.assertEqual(hits[0]["text"], "evidence")

    def test_citation_rejection_and_acceptance(self):
        from langchain_core.language_models.fake import FakeListLLM

        sources = [{"citation_id": "S1"}]
        self.assertIn(
            "enough evidence",
            generate_answer("question", "context", sources, FakeListLLM(responses=["Fact [S2]"])),
        )
        answer = generate_answer(
            "question", "context", sources, FakeListLLM(responses=["Fact [S1]"])
        )
        self.assertEqual(answer, "Fact [S1]")
        self.assertIn("enough evidence", generate_answer("question", "", []))

    def test_reranking_reorders_actual_sources(self):
        class Store:
            field = "chunk_text"

            def search_documents(self, q, strategy, top_k):
                return {
                    "matches": [
                        {"_id": "wrong", "chunk_text": "Wrong period"},
                        {"_id": "right", "chunk_text": "Correct year evidence"},
                    ]
                }

        rag = FinancialRAG(store=Store(), reranker=lambda q, cs: list(reversed(cs)))
        with (
            patch(
                "financial_rag.pipeline.assemble_context",
                side_effect=lambda cs: (
                    "context",
                    [{**c, "citation_id": f"S{i + 1}"} for i, c in enumerate(cs)],
                ),
            ),
            patch("financial_rag.pipeline.generate_answer", return_value="Answer [S1]"),
        ):
            result = rag.answer("Question", final_k=1)
        self.assertEqual(result["sources"][0]["id"], "right")
        self.assertEqual(result["candidate_ids"], ["wrong", "right"])

    def test_reference_fixed_offsets(self):
        text = "Revenue rose. " * 100
        chunks = split_block(
            {"kind": "text", "text": text, "block_id": "a", "document_id": "doc"}, "fixed"
        )
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c["text"]) <= 512 for c in chunks))
        for c in chunks:
            self.assertEqual(c["text"], text[c["start_char"] : c["end_char"]])

    def test_numeric_check_is_not_a_correctness_claim(self):
        self.assertFalse(numeric_reference_present("177,5560", ["177,556"]))
        self.assertTrue(numeric_reference_present("177,556 million", ["177,556"]))
        self.assertTrue(numeric_reference_present("177556.0 million", ["177,556"]))
        self.assertIsNone(
            summarize([{"configuration": "x", "error": "failure"}])[0]["numeric_reference_presence"]
        )

    def test_reference_semantic_retains_normalized_source_evidence(self):
        from langchain_core.embeddings import Embeddings

        class EmbeddingFixture(Embeddings):
            def embed_documents(self, texts):
                return [[1, i + 1] for i in range(len(texts))]

            def embed_query(self, text):
                return [1, 1]

        text = "Revenue rose.\n\nMargins increased. Supply chains improved. Demand expanded."
        chunks = split_block(
            {"kind": "text", "text": text, "block_id": "a", "document_id": "doc"},
            "semantic",
            EmbeddingFixture(),
        )
        self.assertTrue(chunks)
        for c in chunks:
            self.assertIn("".join(c["text"].split()), "".join(text.split()))
            self.assertEqual(c["source_block_id"], "a")
