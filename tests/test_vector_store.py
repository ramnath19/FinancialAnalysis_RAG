import unittest

from financial_rag.vector_store import PineconeStore, vector_metadata


class StoreTests(unittest.TestCase):
    def test_namespaces_isolate_strategy_and_model(self):
        store = PineconeStore.__new__(PineconeStore)
        store.prefix = "test"
        self.assertNotEqual(store.namespace("fixed", "m"), store.namespace("semantic", "m"))
        self.assertNotEqual(store.namespace("fixed", "m"), store.namespace("fixed", "other"))

    def test_reject_dimension_mismatch_before_upload(self):
        store = PineconeStore.__new__(PineconeStore)
        store.prefix = "test"
        calls = []

        def request(path, body):
            calls.append(path)
            return {"dimension": 3}

        store.request = request

        class Embed:
            model_name = "m"

            def __call__(self, texts):
                return [[1, 0]]

        with self.assertRaisesRegex(ValueError, "dimensions"):
            store.upload([{"strategy": "fixed", "text": "example"}], Embed(), "fixed")
        self.assertEqual(calls, ["/describe_index_stats"])

    def test_nested_locations_are_serialized(self):
        metadata = vector_metadata(
            {"text": "example", "location": {"pdf_page": 2}, "config": {}}, "m"
        )
        self.assertEqual(metadata["location_json"], '{"pdf_page": 2}')
        self.assertNotIn("config", metadata)

    def test_document_upload_sends_text_without_external_embedding(self):
        from unittest.mock import Mock

        from financial_rag.vector_store import PineconeDocumentStore

        store = PineconeDocumentStore.__new__(PineconeDocumentStore)
        store.prefix = "test"
        store.model = "text-embedding-3-small"
        store.field = "chunk_text"
        store.index = Mock()
        chunk = dict(
            chunk_id="id",
            strategy="fixed",
            text="Source passage",
            document_id="doc",
            location={"pdf_page": 2},
        )
        store.upload_documents([chunk], "fixed")
        doc = store.index.documents.upsert.call_args.kwargs["documents"][0]
        self.assertEqual(doc["chunk_text"], "Source passage")
        self.assertEqual(doc["_id"], "id")
        self.assertNotIn("values", doc)
