from typing import Protocol

from app.domain.retrieval import GeneratedAnswer, GenerationInput, IndexVersion, RetrievedChunk


class RetrievalStore(Protocol):
    def scope(self, user_id: str, resource_ids: list[str]) -> dict[str, IndexVersion | None]: ...
    def search(self, user_id: str, resource_ids: list[str], vector: list[float],
               model: str, dimensions: int, top_k: int) -> list[RetrievedChunk]: ...


class AnswerGenerator(Protocol):
    def generate(self, prompt: GenerationInput) -> GeneratedAnswer: ...


class RetrievalOptions(Protocol):
    embedding_model: str
    embedding_dimensions: int
    answer_context_budget_bytes: int
