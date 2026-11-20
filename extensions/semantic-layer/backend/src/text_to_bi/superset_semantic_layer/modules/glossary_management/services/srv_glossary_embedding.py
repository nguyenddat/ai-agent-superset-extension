import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import requests

from text_to_bi.superset_semantic_layer.common.utils.similarity import tfidf_vectors
from text_to_bi.superset_semantic_layer.core.config import settings

from ..dependencies import text_embedding_repository

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 64
EMBEDDING_TIMEOUT_SECONDS = 20
# What a failed or malformed embedding call raises; a database error is not among them and is not hidden.
EMBEDDING_FAILURES = (requests.RequestException, ValueError, KeyError, TypeError, IndexError)


@dataclass(frozen=True)
class TextVectors:
    method: str
    model: str | None
    vectors: list[Any]


def text_vectors(texts: list[str]) -> TextVectors:
    model = settings.OPENROUTER_EMBEDDING_MODEL.strip()
    if texts and settings.OPENROUTER_API_KEY and model:
        try:
            return TextVectors("embedding", model, _embedded_vectors(texts, model))
        except EMBEDDING_FAILURES as error:
            logger.warning("Embedding with %s failed (%s); grouping compares words.", model, type(error).__name__)
    return TextVectors("tfidf", None, tfidf_vectors(texts))


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _embedded_vectors(texts: list[str], model: str) -> list[list[float]]:
    repository = text_embedding_repository()
    hashes = [text_hash(text) for text in texts]
    vectors = repository.read_vectors(model, sorted(set(hashes)))
    text_by_hash = dict(zip(hashes, texts))
    missing = [content_hash for content_hash in text_by_hash if content_hash not in vectors]
    for start in range(0, len(missing), EMBEDDING_BATCH_SIZE):
        batch = missing[start:start + EMBEDDING_BATCH_SIZE]
        embedded = _requested_vectors([text_by_hash[content_hash] for content_hash in batch], model)
        for content_hash, vector in zip(batch, embedded):
            vectors[content_hash] = vector
            # Suggestions are read operations; missing vectors stay in memory.
            # Cache population belongs to a separate write operation.
    return [vectors[content_hash] for content_hash in hashes]


def _requested_vectors(texts: list[str], model: str) -> list[list[float]]:
    response = requests.post(
        f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
        json={"model": model, "input": texts},
        timeout=EMBEDDING_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    items = sorted(response.json()["data"], key=lambda item: item["index"])
    # Six decimals keep the cached JSON small and change no similarity that matters.
    vectors = [[round(float(value), 6) for value in item["embedding"]] for item in items]
    if len(vectors) != len(texts) or not vectors[0] or any(len(vector) != len(vectors[0]) for vector in vectors):
        raise ValueError("The embedding response does not match the texts.")
    return vectors
