import math
from typing import Protocol

import httpx

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
        self.settings, self.client = settings, client

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            response = self.client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": "Bearer " + self.settings.openai_api_key.get_secret_value()},
                json={"model": self.settings.embedding_model, "input": texts,
                      "dimensions": self.settings.embedding_dimensions, "encoding_format": "float"},
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise EmbeddingError("Embedding provider request failed", True) from None
        if not response.is_success:
            raise EmbeddingError("Embedding provider rejected the request",
                                 response.status_code == 429 or response.status_code >= 500)
        try:
            data = response.json()["data"]
            if not isinstance(data, list) or len(data) != len(texts):
                raise ValueError
            by_index = {}
            for item in data:
                index = item["index"]
                if type(index) is not int or index < 0 or index >= len(texts) or index in by_index:
                    raise ValueError
                by_index[index] = item["embedding"]
            return validate_vectors([by_index[i] for i in range(len(texts))], len(texts),
                                    self.settings.embedding_dimensions)
        except (ValueError, TypeError, KeyError):
            raise EmbeddingError("Embedding provider returned an invalid response") from None
