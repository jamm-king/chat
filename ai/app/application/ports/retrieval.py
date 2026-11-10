from collections.abc import Callable
from typing import Protocol

from app.domain.retrieval import GeneratedAnswer, GenerationInput, IndexVersion, RetrievedChunk


class RetrievalStore(Protocol):
    def scope(self, user_id: str, resource_ids: list[str]) -> dict[str, IndexVersion | None]: ...
    def search(self, user_id: str, resource_ids: list[str], vector: list[float],
               model: str, dimensions: int, top_k: int) -> list[RetrievedChunk]: ...


class AnswerGenerator(Protocol):
    def generate(self, prompt: GenerationInput) -> GeneratedAnswer: ...


class AutoAnswerGenerator(Protocol):
    def generate_auto(self, prompt: GenerationInput,
                      search: Callable[[str, int, int], GenerationInput],
                      check_active: Callable[[], None]) -> GeneratedAnswer:
        """Call search at most once with query, top_k and measured continuation bytes.

        Authenticated user/resource IDs are captured by the application callback.
        """
        ...


class RetrievalOptions(Protocol):
    embedding_model: str
    embedding_dimensions: int
    answer_context_budget_bytes: int
