from collections.abc import Callable

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings
from app.embeddings import EmbeddingClient, validate_vectors

CHUNKING_VERSION = "recursive-character-v1"


class IndexingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DocumentIndexer:
    def __init__(self, settings: Settings, embeddings: EmbeddingClient):
        self.settings, self.embeddings = settings, embeddings
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", "。", ". ", " ", ""], add_start_index=True,
        )

    def chunks(self, document: Document) -> list[Document]:
        if document.metadata.get("content_status") != "complete":
            raise IndexingError("CONTENT_INCOMPLETE", "Partial content cannot be indexed")
        # Keep original text and provenance. Do not copy full raw_content/references into every chunk.
        metadata = {name: document.metadata.get(name) for name in ("title", "source", "page_id")}
        chunks = self.splitter.split_documents([Document(page_content=document.page_content, metadata=metadata)])
        chunks = [chunk for chunk in chunks if chunk.page_content.strip()]
        if not chunks:
            raise IndexingError("EMPTY_CONTENT", "There is no text to index")
        for sequence, chunk in enumerate(chunks):
            chunk.metadata["sequence"] = sequence
        return chunks

    def embed(self, chunks: list[Document], check_active: Callable[[], None]) -> list[list[float]]:
        vectors = []
        for offset in range(0, len(chunks), self.settings.embedding_batch_size):
            check_active()
            batch = chunks[offset:offset + self.settings.embedding_batch_size]
            result = self.embeddings.embed_documents([chunk.page_content for chunk in batch])
            vectors.extend(validate_vectors(result, len(batch), self.settings.embedding_dimensions))
        check_active()
        return vectors
