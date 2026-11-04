from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class IndexVersion:
    model: str
    dimensions: int
    indexed_at: datetime
    chunk_count: int


@dataclass(frozen=True)
class RetrievedChunk:
    resource_id: str
    chunk_id: str
    title: str | None
    content: str
    url: str
    section: str | None = None


@dataclass(frozen=True)
class EvidenceCitation:
    chunk_id: str
    excerpt: str


@dataclass(frozen=True)
class GeneratedAnswer:
    status: Literal["ANSWERED", "INSUFFICIENT_EVIDENCE", "REFUSED"]
    content: str
    citations: list[EvidenceCitation]


@dataclass(frozen=True)
class GenerationInput:
    mode: str
    message: str
    history: list[tuple[str, str]]
    evidence: list[RetrievedChunk]
