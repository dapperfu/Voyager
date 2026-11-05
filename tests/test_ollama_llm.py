"""Mocked tests for the Ollama client. No Minecraft process and no Ollama server."""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import the client without executing voyager/__init__.py, which loads the game env.
if "voyager" not in sys.modules:
    package = types.ModuleType("voyager")
    package.__path__ = [str(ROOT / "voyager")]
    package.__package__ = "voyager"
    sys.modules["voyager"] = package

from langchain.schema import AIMessage, HumanMessage, SystemMessage
from voyager.llm import (
    OllamaChat,
    OllamaEmbeddings,
    prepare_vectordb_dir,
    vectordb_needs_rebuild,
    write_embedding_model,
)


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        return self._payload


class OllamaChatTest(unittest.TestCase):
    def test_chat_sends_roles_temperature_and_num_ctx(self):
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return _Response(200, {"message": {"role": "assistant", "content": "hello"}})

        chat = OllamaChat(
            model="qwen2.5-coder:7b",
            base_url="http://127.0.0.1:11434",
            temperature=0,
            timeout=240,
            num_ctx=8192,
        )
        with mock.patch("voyager.llm.requests.post", side_effect=fake_post):
            result = chat(
                [
                    SystemMessage(content="sys"),
                    HumanMessage(content="hi"),
                    AIMessage(content="prior"),
                ]
            )

        self.assertEqual(captured["url"], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(captured["timeout"], 240)
        self.assertEqual(
            captured["json"]["messages"],
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "prior"},
            ],
        )
        self.assertEqual(captured["json"]["options"]["temperature"], 0)
        self.assertEqual(captured["json"]["options"]["num_ctx"], 8192)
        self.assertFalse(captured["json"]["stream"])
        self.assertNotIn("format", captured["json"])
        self.assertIsInstance(result, AIMessage)
        self.assertEqual(result.content, "hello")

    def test_connection_error_names_server_and_model(self):
        chat = OllamaChat(model="qwen2.5-coder:7b", base_url="http://127.0.0.1:11434/")
        with mock.patch(
            "voyager.llm.requests.post",
            side_effect=requests.ConnectionError("refused"),
        ):
            with self.assertRaises(RuntimeError) as caught:
                chat([HumanMessage(content="hi")])
        message = str(caught.exception)
        self.assertIn("http://127.0.0.1:11434", message)
        self.assertIn("qwen2.5-coder:7b", message)

    def test_model_not_found_names_server_and_model(self):
        chat = OllamaChat(model="missing-model", base_url="http://127.0.0.1:11434")

        def fake_post(url, json=None, timeout=None):
            return _Response(404, {"error": "model not found"})

        with mock.patch("voyager.llm.requests.post", side_effect=fake_post):
            with self.assertRaises(RuntimeError) as caught:
                chat([HumanMessage(content="hi")])
        message = str(caught.exception)
        self.assertIn("http://127.0.0.1:11434", message)
        self.assertIn("missing-model", message)


class OllamaEmbeddingsTest(unittest.TestCase):
    def test_embed_uses_api_embed(self):
        inputs = []

        def fake_post(url, json=None, timeout=None):
            self.assertTrue(url.endswith("/api/embed"))
            inputs.append(json["input"])
            table = {"a": [0.1, 0.2], "b": [0.3, 0.4]}
            return _Response(
                200, {"embeddings": [table[text] for text in json["input"]]}
            )

        embeddings = OllamaEmbeddings(
            model="nomic-embed-text", base_url="http://127.0.0.1:11434"
        )
        with mock.patch("voyager.llm.requests.post", side_effect=fake_post):
            vectors = embeddings.embed_documents(["a", "b"])
            one = embeddings.embed_query("a")

        self.assertEqual(inputs, [["a", "b"], ["a"]])
        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])
        self.assertEqual(one, [0.1, 0.2])

    def test_embed_falls_back_when_api_embed_is_missing(self):
        prompts = []

        def fake_post(url, json=None, timeout=None):
            if url.endswith("/api/embed"):
                return _Response(404, "404 page not found")
            prompts.append(json["prompt"])
            return _Response(200, {"embedding": [0.5, 0.6]})

        embeddings = OllamaEmbeddings(model="nomic-embed-text")
        with mock.patch("voyager.llm.requests.post", side_effect=fake_post):
            vectors = embeddings.embed_documents(["a", "b"])

        self.assertEqual(prompts, ["a", "b"])
        self.assertEqual(vectors, [[0.5, 0.6], [0.5, 0.6]])


class EmbeddingMarkerTest(unittest.TestCase):
    def test_nonempty_store_without_matching_marker_needs_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            vectordb = Path(tmp) / "vectordb"
            marker = Path(tmp) / "embedding.json"
            self.assertFalse(vectordb_needs_rebuild(str(vectordb), str(marker), "nomic-embed-text"))
            vectordb.mkdir()
            self.assertFalse(vectordb_needs_rebuild(str(vectordb), str(marker), "nomic-embed-text"))
            (vectordb / "index.bin").write_text("old", encoding="utf-8")
            self.assertTrue(vectordb_needs_rebuild(str(vectordb), str(marker), "nomic-embed-text"))
            write_embedding_model(str(marker), "nomic-embed-text")
            self.assertFalse(vectordb_needs_rebuild(str(vectordb), str(marker), "nomic-embed-text"))
            self.assertTrue(vectordb_needs_rebuild(str(vectordb), str(marker), "other-model"))

    def test_prepare_deletes_a_foreign_store_and_keeps_a_fresh_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            vectordb = Path(tmp) / "vectordb"
            marker = Path(tmp) / "embedding.json"
            vectordb.mkdir()
            (vectordb / "index.bin").write_text("old", encoding="utf-8")
            self.assertTrue(
                prepare_vectordb_dir(str(vectordb), str(marker), "nomic-embed-text")
            )
            self.assertTrue(vectordb.is_dir())
            self.assertEqual(list(vectordb.iterdir()), [])

            self.assertFalse(
                prepare_vectordb_dir(str(vectordb), str(marker), "nomic-embed-text")
            )
            self.assertTrue(vectordb.is_dir())


if __name__ == "__main__":
    unittest.main()
