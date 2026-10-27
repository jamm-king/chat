import uuid
from typing import Optional, List, Dict, Any
from sqlalchemy import String, Text, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    resource_id: Mapped[str] = mapped_column(String(36), ForeignKey("resources.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)  # 임베딩 벡터 데이터 저장용
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_locator: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    resource: Mapped["Resource"] = relationship("Resource", back_populates="chunks")
    citations: Mapped[List["Citation"]] = relationship("Citation", back_populates="chunk", cascade="all, delete-orphan")