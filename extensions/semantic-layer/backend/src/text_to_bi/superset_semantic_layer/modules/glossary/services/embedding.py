import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from ....common.utils.similarity import tfidf_vectors
from ....core.config import settings
from ..dependencies import text_embedding_repository
from ..models import TextEmbedding

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 64
EMBEDDING_TIMEOUT_SECONDS = 20
# What a failed or malformed embedding call raises; a database error is not among them and is not hidden.
EMBEDDING_FAILURES = (requests.RequestException, ValueError, KeyError, TypeError, IndexError)


@dataclass(frozen=True)
class TextVectors:
    """Vectors of some texts and how they were made: `embedding` by `model`, or `tfidf` from the texts' own words."""

    method: str
    model: str | None
    vectors: list[Any]


def text_vectors(texts: list[str]) -> TextVectors:
    """Vectors of the texts from the configured embedding model, or TF-IDF vectors when it cannot be used.

    The remote model reads meaning across wording ("mưa to" and "lượng mưa lớn"); TF-IDF only matches shared words,
    but needs no key or network, so suggestions still work locally and when OpenRouter fails. One method covers all
    the texts, because similarities from the two are not comparable. New vectors are added to the session as cache
    rows for the caller to commit.
    """
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
    """The model's vectors of the texts: cached ones by text hash, the rest requested and added to the cache."""
    repository = text_embedding_repository()
    hashes = [text_hash(text) for text in texts]
    vectors = repository.vectors_for(model, sorted(set(hashes)))
    text_by_hash = dict(zip(hashes, texts))
    missing = [content_hash for content_hash in text_by_hash if content_hash not in vectors]
    for start in range(0, len(missing), EMBEDDING_BATCH_SIZE):
        batch = missing[start:start + EMBEDDING_BATCH_SIZE]
        embedded = _requested_vectors([text_by_hash[content_hash] for content_hash in batch], model)
        created_at = datetime.now(timezone.utc)
        for content_hash, vector in zip(batch, embedded):
            vectors[content_hash] = vector
            repository.add(
                TextEmbedding(model=model, content_hash=content_hash, vector=vector, created_at=created_at), flush=False
            )
    return [vectors[content_hash] for content_hash in hashes]


def _requested_vectors(texts: list[str], model: str) -> list[list[float]]:
    """Vectors from OpenRouter's OpenAI-compatible embeddings endpoint, in the order of the texts."""
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
