import uuid
from typing import Optional, Dict, Any
from sqlalchemy import String, Text, ForeignKey, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), ForeignKey("resources.id", ondelete="CASCADE"), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # 답변 본문의 [1], [2] 표시와 매칭되는 순서 (1부터 시작)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    message: Mapped["Message"] = relationship("Message", back_populates="citations")
    resource: Mapped["Resources"] = relationship("Resources", back_populates="citations")
    