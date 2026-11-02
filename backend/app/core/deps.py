from fastapi import Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import verify_token
from app.db.session import get_db
from app.models.users import User


bearer_scheme = HTTPBearer(auto_error=False)


# 인증이 필요한 API에서 사용하는 현재 사용자 의존성
# 에러 코드는 GET /api/v1/users/me 와 동일하게 맞춘다.
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> User:
    if credentials is None:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_MISSING_TOKEN",
            "인증 토큰이 필요합니다."
        )

    payload = verify_token(credentials.credentials)

    if not payload:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_INVALID_ACCESS_TOKEN",
            "유효하지 않은 액세스 토큰입니다."
        )

    if payload.get("type") != "access":
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_INVALID_TOKEN_TYPE",
            "Access Token이 아닙니다."
        )

    email = payload.get("sub")

    if not email:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_TOKEN_USER_MISSING",
            "토큰에 사용자 정보가 없습니다."
        )

    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "USER_NOT_FOUND",
            "사용자를 찾을 수 없습니다."
        )

    return user
