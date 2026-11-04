from collections.abc import Callable

from app.application.ports.documents import EmbeddingClient, PipelineOptions, TextChunker
from app.domain.documents import TextDocument
from app.domain.errors import IndexingError
from app.domain.vectors import validate_vectors


class DocumentIndexer:
    def __init__(self, settings: PipelineOptions, embeddings: EmbeddingClient, chunker: TextChunker):
        self.settings, self.embeddings, self.chunker = settings, embeddings, chunker
        self.chunking_version = chunker.version

    def chunks(self, document: TextDocument) -> list[TextDocument]:
        if document.metadata.get("content_status") != "complete":
            raise IndexingError("CONTENT_INCOMPLETE", "Partial content cannot be indexed")
        metadata = {name: document.metadata.get(name) for name in ("title", "source", "page_id")}
        chunks = self.chunker.split(TextDocument(document.page_content, metadata))
        chunks = [chunk for chunk in chunks if chunk.page_content.strip()]
        if not chunks:
            raise IndexingError("EMPTY_CONTENT", "There is no text to index")
        for sequence, chunk in enumerate(chunks):
            chunk.metadata["sequence"] = sequence
        return chunks

    def embed(self, chunks: list[TextDocument], check_active: Callable[[], None]) -> list[list[float]]:
        vectors = []
        for offset in range(0, len(chunks), self.settings.embedding_batch_size):
            check_active()
            batch = chunks[offset:offset + self.settings.embedding_batch_size]
            result = self.embeddings.embed_documents([chunk.page_content for chunk in batch])
            vectors.extend(validate_vectors(result, len(batch), self.settings.embedding_dimensions))
        check_active()
        return vectors
