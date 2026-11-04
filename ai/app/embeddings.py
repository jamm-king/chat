import math
from typing import Protocol

import httpx
from langchain_openai import OpenAIEmbeddings
from openai import APIConnectionError, APIStatusError, OpenAIError

from app.config import Settings


class EmbeddingError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class EmbeddingClient(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


def validate_vectors(vectors, count: int, dimensions: int) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != count:
        raise EmbeddingError("Embedding response count does not match input")
    output = []
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise EmbeddingError("Embedding dimensions do not match configuration")
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in vector):
            raise EmbeddingError("Embedding response contains invalid values")
        if not any(value != 0 for value in vector):
            raise EmbeddingError("Embedding response contains a zero vector")
        output.append([float(value) for value in vector])
    return output


class OpenAIEmbeddingClient:
    def __init__(self, settings: Settings, client: httpx.Client):
        self.settings = settings
        self.embeddings = OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            base_url="https://api.openai.com/v1",
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            chunk_size=settings.embedding_batch_size,
            check_embedding_ctx_length=False,
            max_retries=0,
            request_timeout=settings.embedding_timeout_seconds,
            http_client=client,
            model_kwargs={"encoding_format": "float"},
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = self.embeddings.embed_documents(texts)
        except APIConnectionError:
            raise EmbeddingError("Embedding provider request failed", True) from None
        except APIStatusError as error:
            raise EmbeddingError("Embedding provider rejected the request",
                                 error.status_code == 429 or error.status_code >= 500) from None
        except (OpenAIError, ValueError, TypeError, KeyError, AttributeError):
            raise EmbeddingError("Embedding provider returned an invalid response") from None
        return validate_vectors(vectors, len(texts), self.settings.embedding_dimensions)
