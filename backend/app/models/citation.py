import uuid
from typing import Optional, Dict, Any
from sqlalchemy import String, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), ForeignKey("resources.id", ondelete="CASCADE"), nullable=False)
    chunk_id: Mapped[str] = mapped_column(String(36), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    message: Mapped["Message"] = relationship("Message", back_populates="citations")
    resource: Mapped["Resource"] = relationship("Resource", back_populates="citations")
    chunk: Mapped["Chunk"] = relationship("Chunk", back_populates="citations")






    