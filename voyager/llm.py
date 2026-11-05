"""Ollama chat and embedding clients used by the Voyager agents."""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Optional

import requests
from langchain.schema import AIMessage, HumanMessage, SystemMessage

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_CHAT_MODEL = "qwen2.5-coder:7b"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_NUM_CTX = 8192
DEFAULT_TIMEOUT = 240


def _message_role(message: Any) -> str:
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    raise TypeError(f"Unsupported message type: {type(message)}")


def _pull_hint(base_url: str, model: str, detail: str) -> RuntimeError:
    return RuntimeError(
        f"Cannot use Ollama model {model} at {base_url}. "
        f"Start the server with ollama serve and pull the model with "
        f"ollama pull {model}. {detail}"
    )


def _post_json(
    *,
    base_url: str,
    path: str,
    payload: dict,
    model: str,
    timeout: int,
    allow_not_found: bool = False,
) -> Optional[dict]:
    url = f"{base_url}{path}"
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.ConnectionError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {base_url}. "
            f"Start it with ollama serve and pull {model}."
        ) from exc
    if allow_not_found and response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise _pull_hint(base_url, model, response.text)
    return response.json()


class OllamaChat:
    """Chat model that posts one non-streaming request to Ollama `/api/chat`."""

    def __init__(
        self,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        temperature: float = 0,
        timeout: int = DEFAULT_TIMEOUT,
        num_ctx: int = DEFAULT_NUM_CTX,
    ):
        self.model = model
        # ActionAgent reads model_name to decide which control primitives to include.
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout
        self.num_ctx = num_ctx

    def __call__(self, messages) -> AIMessage:
        body = _post_json(
            base_url=self.base_url,
            path="/api/chat",
            payload={
                "model": self.model,
                "messages": [
                    {"role": _message_role(message), "content": message.content}
                    for message in messages
                ],
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_ctx": self.num_ctx,
                },
            },
            model=self.model,
            timeout=self.timeout,
        )
        return AIMessage(content=body["message"]["content"])


class OllamaEmbeddings:
    """Embedding function with the `embed_query` / `embed_documents` methods Chroma calls."""

    def __init__(
        self,
        model: str = DEFAULT_EMBEDDING_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.model = model
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = _post_json(
            base_url=self.base_url,
            path="/api/embed",
            payload={"model": self.model, "input": list(texts)},
            model=self.model,
            timeout=self.timeout,
            allow_not_found=True,
        )
        if body is None:
            return [self._embed_legacy(text) for text in texts]
        embeddings = body["embeddings"]
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Ollama at {self.base_url} returned {len(embeddings)} embeddings "
                f"for {len(texts)} texts."
            )
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def _embed_legacy(self, text: str) -> list[float]:
        body = _post_json(
            base_url=self.base_url,
            path="/api/embeddings",
            payload={"model": self.model, "prompt": text},
            model=self.model,
            timeout=self.timeout,
        )
        return body["embedding"]


def build_chat_model(
    *,
    model_name: str,
    temperature: float,
    request_timeout: int,
    base_url: str,
    num_ctx: int,
) -> OllamaChat:
    return OllamaChat(
        model=model_name,
        base_url=base_url,
        temperature=temperature,
        timeout=request_timeout,
        num_ctx=num_ctx,
    )


def build_embeddings(
    *,
    model_name: str,
    base_url: str,
    request_timeout: int,
) -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=model_name,
        base_url=base_url,
        timeout=request_timeout,
    )


def read_embedding_model(marker_path: str) -> Optional[str]:
    if not os.path.isfile(marker_path):
        return None
    with open(marker_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    model = data.get("model")
    if not isinstance(model, str):
        return None
    return model


def write_embedding_model(marker_path: str, model_name: str) -> None:
    parent = os.path.dirname(marker_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(marker_path, "w", encoding="utf-8") as handle:
        json.dump({"model": model_name}, handle)


def _directory_has_entries(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    with os.scandir(path) as entries:
        return any(entries)


def vectordb_needs_rebuild(vectordb_dir: str, marker_path: str, model_name: str) -> bool:
    """A non-empty store is reusable only when its marker names this embedding model."""
    if not _directory_has_entries(vectordb_dir):
        return False
    return read_embedding_model(marker_path) != model_name


def prepare_vectordb_dir(vectordb_dir: str, marker_path: str, model_name: str) -> bool:
    """Delete a store embedded by another model. Return True when the caller must re-embed."""
    rebuild = vectordb_needs_rebuild(vectordb_dir, marker_path, model_name)
    if rebuild:
        shutil.rmtree(vectordb_dir)
    os.makedirs(vectordb_dir, exist_ok=True)
    return rebuild
