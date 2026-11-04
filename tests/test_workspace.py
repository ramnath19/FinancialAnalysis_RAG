"""Validation, cached read models and logging privacy regressions."""

import io
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from financial_rag.logging_config import (
    LOGGER,
    REQUEST_ID,
    JsonFormatter,
    PrivateRotatingHandler,
    configure_logging,
    event,
)
from financial_rag.registry import Registry, atomic_write
from financial_rag.workspace import AskRequest, Workspace


class RequestValidationTests(unittest.TestCase):
    def test_defaults_and_trim(self):
        request = AskRequest.parse({"question": "  Apple revenue?  "})
        self.assertEqual(request.question, "Apple revenue?")
        self.assertEqual(request.strategy, "fixed")
        self.assertEqual(request.context["tickers"], [])

    def test_invalid_context_and_settings(self):
        invalid = [
            {"question": ""},
            {"question": "a" * 2001},
            {"question": 4},
            {"strategy": "../secret"},
            {"rerank": "yes"},
            {"offline": 1},
            {"mode": "unknown"},
            {"selector": "../../.env"},
            {"context": []},
            {"context": {"tickers": [3]}},
            {"context": {"tickers": ["../../file"]}},
            {"context": {"tickers": ["AAPL"] * 5}},
            {"context": {"year": "20x5"}},
            {"context": {"year": 2025}},
            {"context": {"topic": {"bad": "type"}}},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                AskRequest.parse({"question": "Apple revenue?", **changes})


class WorkspaceTests(unittest.TestCase):
    def test_chunk_cache_invalidates_and_never_reads_arbitrary_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "data/chunks/reference"
            folder.mkdir(parents=True)
            path = folder / "fixed.jsonl"
            atomic_write(path, json.dumps({"text": "short"}) + "\n")
            workspace = Workspace(Registry(root))
            first = workspace.chunks("fixed")
            self.assertEqual(first["max_characters"], 5)
            self.assertIs(first, workspace.chunks("fixed"))
            atomic_write(path, json.dumps({"text": "longer sample"}) + "\n")
            self.assertEqual(workspace.chunks("fixed")["max_characters"], 13)
            with self.assertRaises(ValueError):
                workspace.chunks("../../.env")

    def test_session_strategy_capabilities_are_corpus_specific(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "data/manifest.json").write_text("[]")
            registry = Registry(root)
            registry.register(
                {
                    "ticker": "TSLA",
                    "documents": [{"document_id": "t", "ticker": "TSLA", "company": "Tesla"}],
                }
            )
            folder = root / "data/session/TSLA"
            folder.mkdir()
            (folder / "fixed.jsonl").write_text("{}\n")
            (folder / "section.jsonl").write_text("{}\n")
            self.assertEqual(registry.strategies("TSLA"), ["fixed", "section"])
            self.assertEqual(registry.strategies("TSLA", "bundled"), [])

    def test_failed_atomic_publish_keeps_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            path.write_text("original")
            with patch.object(Path, "replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    atomic_write(path, "replacement")
            self.assertEqual(path.read_text(), "original")
            self.assertEqual(list(Path(directory).iterdir()), [path])


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.handlers = LOGGER.handlers[:]
        self.level = LOGGER.level
        self.propagate = LOGGER.propagate
        for handler in self.handlers:
            LOGGER.removeHandler(handler)

    def tearDown(self):
        for handler in list(LOGGER.handlers):
            LOGGER.removeHandler(handler)
            handler.close()
        for handler in self.handlers:
            LOGGER.addHandler(handler)
        LOGGER.setLevel(self.level)
        LOGGER.propagate = self.propagate

    def test_redaction_request_correlation_and_exception_privacy(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(JsonFormatter())
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)
        token = REQUEST_ID.set("test-request")
        try:
            with patch.dict(os.environ, {"TEST_API_KEY": "secret-value\nsecond-line"}):
                event(
                    "test.event",
                    nested={"value": "secret-value\nsecond-line"},
                    authorization="Bearer abcdef12345",
                )
                try:
                    raise RuntimeError("a confidential user prompt and secret-value")
                except RuntimeError:
                    LOGGER.exception("test.failure")
        finally:
            REQUEST_ID.reset(token)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(records[0]["request_id"], "test-request")
        self.assertEqual(records[0]["nested"]["value"], "[REDACTED]")
        self.assertNotIn("abcdef12345", output.getvalue())
        self.assertNotIn("confidential user prompt", output.getvalue())
        self.assertEqual(records[1]["error_type"], "RuntimeError")

    def test_configuration_is_idempotent_and_rotated_files_are_private(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("sys.stderr", new=io.StringIO()):
                path = configure_logging(directory)
                configure_logging(directory)
                self.assertEqual(len(LOGGER.handlers), 2)
                handler = next(h for h in LOGGER.handlers if isinstance(h, PrivateRotatingHandler))
                handler.doRollover()
                event("test.after_rotation")
                handler.flush()
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(path.read_text())["event"], "test.after_rotation")


class RetrievalFallbackTests(unittest.TestCase):
    def test_local_only_preserves_vector_selection_and_skips_provider(self):
        from financial_rag.retrieval import Retriever

        retriever = Retriever()
        chunk = {"id": "local", "text": "revenue", "metadata": {"document_id": "d"}}
        index = unittest.mock.Mock()
        index.search.return_value = [chunk]
        with (
            patch.object(retriever, "index", return_value=index),
            patch.object(
                retriever.registry,
                "documents",
                return_value=[{"document_id": "d", "ticker": "AAPL"}],
            ),
            patch("financial_rag.vector_store.PineconeDocumentStore") as remote,
        ):
            hits, backend = retriever.search("revenue", ["AAPL"], mode="vector", offline=True)
        remote.assert_not_called()
        self.assertEqual(index.search.call_count, 1)
        self.assertEqual(index.search.call_args.args[3], "vector")
        self.assertEqual(hits[0]["id"], "local")
        self.assertIn("TF-IDF", backend)

    def test_remote_failure_is_logged_and_recoverable(self):
        from financial_rag.retrieval import Retriever

        retriever = Retriever()
        retriever.store = unittest.mock.Mock()
        retriever.store.search_documents.side_effect = OSError("network down")
        index = unittest.mock.Mock()
        index.search.return_value = [{"id": "local", "metadata": {"document_id": "d"}}]
        with (
            patch.dict(os.environ, {"PINECONE_API_KEY": "dummy-test-only"}),
            patch.object(retriever, "index", return_value=index),
            patch.object(
                retriever.registry,
                "documents",
                return_value=[{"document_id": "d", "ticker": "AAPL"}],
            ),
            patch.object(retriever.registry, "company", return_value={"name": "Apple"}),
            self.assertLogs("financial_rag", level="WARNING") as captured,
        ):
            hits, backend = retriever.search("revenue", ["AAPL"])
        self.assertEqual(hits[0]["id"], "local")
        self.assertIn("TF-IDF", backend)
        self.assertTrue(any("retrieval.remote_fallback" in line for line in captured.output))
