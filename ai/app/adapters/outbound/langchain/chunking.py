from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.domain.documents import TextDocument


class LangChainTextChunker:
    version = "recursive-character-v1"

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", ". ", " ", ""], add_start_index=True,
        )

    def split(self, document: TextDocument) -> list[TextDocument]:
        chunks = self.splitter.split_documents([
            Document(page_content=document.page_content, metadata=document.metadata),
        ])
        return [TextDocument(chunk.page_content, chunk.metadata) for chunk in chunks]
