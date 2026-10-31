import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Boolean,
    DateTime,
    ForeignKey
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship
)

from app.db.base import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    # Refresh Token DB 레코드 ID
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    # 사용자 ID
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "users.id",
            ondelete="CASCADE"
        ),
        nullable=False
    )
    # JWT의 jti
    jti: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        index=True,
        nullable=False
    )
    # 폐기 여부
    is_revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    # Refresh Token 만료 시간
    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False
    )
    # 생성 시간
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    # User와 관계
    user: Mapped["User"] = relationship(
        "User",
        backref="refresh_tokens"
    )