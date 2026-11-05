import uuid
from datetime import datetime,timezone
from typing import Optional, Dict, Any
from sqlalchemy import String, Text, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    # jobId. Backend 가 발급하고 AI 도 같은 ID 를 쓴다
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    resource_id: Mapped[str] = mapped_column(String(36), ForeignKey("resources.id", ondelete="CASCADE"), nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)  # COLLECT, COLLECT_AND_INDEX
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # QUEUED, EXTRACTING, INDEXING, SUCCEEDED, FAILED, CANCELLED, EXTRACTED
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retryable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    resource: Mapped["Resources"] = relationship("Resources", back_populates="ingestion_jobs")
