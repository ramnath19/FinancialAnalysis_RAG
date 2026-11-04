import io
import os
import unittest
from unittest.mock import patch

from financial_rag.remote_embeddings import NebiusEmbedder


class RemoteEmbeddingTests(unittest.TestCase):
    def test_response_order_is_restored(self):
        with patch.dict(os.environ, {"NEBIUS_API_KEY": "test-key"}):
            adapter = NebiusEmbedder("test-embedding-model")
        payload = b'{"data":[{"index":1,"embedding":[0,1]},{"index":0,"embedding":[1,0]}]}'
        with patch("financial_rag.remote_embeddings.urlopen", return_value=io.BytesIO(payload)):
            self.assertEqual(adapter(["first", "second"]), [[1, 0], [0, 1]])

    def test_missing_key_fails_before_network(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "NEBIUS_API_KEY"):
                NebiusEmbedder("embedding")

    def test_openai_uses_separate_credentials_and_endpoint(self):
        from financial_rag.remote_embeddings import configured_embedder

        with patch.dict(
            os.environ, {"OPENAI_API_KEY": "openai-test", "NEBIUS_API_KEY": "nebius-test"}
        ):
            adapter = configured_embedder("openai", "text-embedding-3-small")
        self.assertEqual(adapter.key, "openai-test")
        self.assertEqual(adapter.base_url, "https://api.openai.com/v1")
        self.assertEqual(adapter.model_name, "text-embedding-3-small")

    def test_pinecone_batches_preserve_input_order(self):
        from unittest.mock import Mock

        from financial_rag.remote_embeddings import PineconeEmbedder

        adapter = PineconeEmbedder.__new__(PineconeEmbedder)
        adapter.model_name = "llama-text-embed-v2"
        adapter.client = Mock()

        def embed(**kwargs):
            response = Mock()
            response.to_dict.return_value = {
                "data": [{"values": [int(text), 1]} for text in kwargs["inputs"]]
            }
            return response

        adapter.client.inference.embed.side_effect = embed
        self.assertEqual(adapter([str(i) for i in range(70)]), [[i, 1] for i in range(70)])
