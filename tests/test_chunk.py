import unittest

from financial_rag.chunk import chunk_block, fixed_spans, semantic_spans


class ChunkTests(unittest.TestCase):
    def test_fixed_overlap_and_tail(self):
        self.assertEqual(list(fixed_spans("abcdefghij", 5, 2)), [(0, 5), (3, 8), (6, 10)])
        with self.assertRaises(ValueError):
            list(fixed_spans("abc", 3, 3))

    def test_semantic_boundary_uses_embedding_change(self):
        text = "Revenue rose. Margins grew. Floods disrupted shipping. Repairs continued."

        def embed(texts):
            return [[1, 0], [1, 0], [0, 1], [0, 1]]

        spans = semantic_spans(text, embed, 1000, 50)
        self.assertEqual(len(spans), 2)
        self.assertEqual("".join(text[a:b] for a, b in spans), text)
        self.assertIn("Margins grew.", text[slice(*spans[0])])
        self.assertIn("Floods", text[slice(*spans[1])])

    def test_large_sentence_cap_and_source_offsets(self):
        text = "x" * 100
        spans = semantic_spans(text, lambda texts: [[1, 0]], 25)
        self.assertTrue(all(b - a <= 25 for a, b in spans))
        self.assertEqual("".join(text[a:b] for a, b in spans), text)
        block = dict(
            kind="text", text=text, block_id="source", document_id="doc", location={"pdf_page": 2}
        )
        chunks = chunk_block(block, "fixed", size=30, overlap=5)
        self.assertEqual(chunks[0]["location"], block["location"])
        self.assertEqual(
            chunks[0]["chunk_id"], chunk_block(block, "fixed", size=30, overlap=5)[0]["chunk_id"]
        )
        block["kind"] = "table"
        self.assertEqual(chunk_block(block, "fixed"), [])
