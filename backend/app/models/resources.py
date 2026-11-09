import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from sqlalchemy import String, JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Resources(Base):
    __tablename__ = "resources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # NOTION_PAGE
    source: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)  # {"url": 노션 원본 주소, 수집 전에는 null}
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # PROCESSING, COLLECTED, READY, FAILED, DELETED
    connection_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)  # 노션 연결 ID (AI 가 발급)
    page_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)  # 노션 페이지 ID
    parent_resource_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("resources.id", ondelete="SET NULL"), nullable=True
    )  # 참조 페이지로 등록했을 때 부모 자료
    latest_job_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)  # 최근 처리 작업
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship("User", back_populates="resources")
    ingestion_jobs: Mapped[List["IngestionJob"]] = relationship("IngestionJob", back_populates="resource", cascade="all, delete-orphan")
    citations: Mapped[List["Citation"]] = relationship("Citation", back_populates="resource", cascade="all, delete-orphan")
