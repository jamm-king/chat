import uuid
from datetime import datetime, timezone
from typing import List
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    auth_sessions: Mapped[List["AuthSession"]] = relationship("AuthSession", back_populates="user", cascade="all, delete-orphan")
    resources: Mapped[List["Resource"]] = relationship("Resource", back_populates="user", cascade="all, delete-orphan")
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="user", cascade="all, delete-orphan")