import httpx
from langchain_openai import OpenAIEmbeddings
from openai import APIConnectionError, APIStatusError, OpenAIError

from app.config import Settings
from app.application.ports.documents import EmbeddingClient
from app.domain.errors import EmbeddingError
from app.domain.vectors import validate_vectors


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
