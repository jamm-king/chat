from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TextDocument:
    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredResource:
    identity: tuple[str, str, str, str | None]
    document: TextDocument


@dataclass(frozen=True)
class IndexSpecification:
    model: str
    dimensions: int
    chunk_size: int
    chunk_overlap: int
    chunking_version: str
    indexed_at: datetime
