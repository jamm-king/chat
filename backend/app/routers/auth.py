from datetime import datetime, timezone, timedelta
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status
)
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.users import User
from app.models.refreshtoken import RefreshToken
from app.schemas.auth import (
    UserCreate,
    UserLogin,
    TokenResponse,
    TokenRefreshRequest,
    UserResponse
)
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token,
    REFRESH_TOKEN_EXPIRE_DAYS
)


# Router
router = APIRouter(
    prefix="/api/v1",
    tags=["Auth"]
)

# OAuth2
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login"
)


# 에러 응답 생성
def error_response(
    code: str,
    message: str,
    retryable: bool = False,
    details: list = None
):
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": details or []
        },
        "requestId": str(uuid4())
    }


# 1. 회원가입
@router.post(
    "/auth/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
def signup(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    # 이메일 중복 확인
    existing_user = (
        db.query(User)
        .filter(User.email == user_data.email)
        .first()
    )

    if existing_user:
        return JSONResponse(
            status_code=400,
            content=error_response(
                code="AUTH_EMAIL_ALREADY_EXISTS",
                message="이미 등록된 이메일입니다.",
                retryable=False
            )
        )

    # 사용자 생성
    new_user = User(
        email=user_data.email,
        password_hash=hash_password(
            user_data.password
        )
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


# 2. 로그인
@router.post(
    "/auth/login",
    response_model=TokenResponse
)
def login(
    user_data: UserLogin,
    db: Session = Depends(get_db)
):
    # 사용자 조회
    user = (
        db.query(User)
        .filter(User.email == user_data.email)
        .first()
    )

    # 사용자 존재 여부 + 비밀번호 확인
    if not user or not verify_password(
        user_data.password,
        user.password_hash
    ):
        return JSONResponse(
            status_code=400,
            content=error_response(
                code="AUTH_INVALID_CREDENTIALS",
                message="이메일 또는 비밀번호가 올바르지 않습니다.",
                retryable=False
            )
        )

    # Access Token 생성
    access_token = create_access_token(
        data={"sub": user.email}
    )

    # Refresh Token 생성
    refresh_token_value, jti = create_refresh_token(
        data={"sub": user.email}
    )

    # Refresh Token DB 저장
    db_token = RefreshToken(
        user_id=user.id,
        jti=jti,
        expires_at=(
            datetime.now(timezone.utc)
            + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        )
    )

    db.add(db_token)
    db.commit()

    # 클라이언트에게 토큰 전달
    return {
        "access_token": access_token,
        "refresh_token": refresh_token_value,
        "token_type": "bearer"
    }


# 3. Refresh Token Rotation
@router.post(
    "/auth/refresh",
    response_model=TokenResponse
)
def refresh_access_token(
    body: TokenRefreshRequest,
    db: Session = Depends(get_db)
):
    # 1. Refresh Token JWT 검증
    payload = verify_token(body.refresh_token)

    if not payload:
        return JSONResponse(
            status_code=401,
            content=error_response(
                code="AUTH_INVALID_REFRESH_TOKEN",
                message="유효하지 않거나 만료된 리프레시 토큰입니다.",
                retryable=False
            )
        )

    # 2. 토큰 타입 확인
    if payload.get("type") != "refresh":
        return JSONResponse(
            status_code=401,
            content=error_response(
                code="AUTH_INVALID_TOKEN_TYPE",
                message="Refresh Token이 아닙니다.",
                retryable=False
            )
        )

    # 3. JWT에서 정보 추출
    jti = payload.get("jti")
    email = payload.get("sub")

    if not jti or not email:
        return JSONResponse(
            status_code=401,
            content=error_response(
                code="AUTH_INVALID_REFRESH_TOKEN",
                message="잘못된 리프레시 토큰입니다.",
                retryable=False
            )
        )

    # 4. DB에서 Refresh Token 조회
    db_token = (
        db.query(RefreshToken)
        .filter(RefreshToken.jti == jti)
        .first()
    )

    # 5. DB 토큰 검증
    if not db_token:
        return JSONResponse(
            status_code=401,
            content=error_response(
                code="AUTH_REFRESH_TOKEN_NOT_FOUND",
                message="등록되지 않은 리프레시 토큰입니다.",
                retryable=False
            )
        )

    # 이미 사용된 Refresh Token인지 확인
    if db_token.is_revoked:
        return JSONResponse(
            status_code=401,
            content=error_response(
                code="AUTH_REFRESH_TOKEN_REVOKED",
                message="이미 폐기된 리프레시 토큰입니다.",
                retryable=False
            )
        )

    # DB 기준 만료 여부 확인
    now = datetime.now(timezone.utc)

    if db_token.expires_at < now:
        return JSONResponse(
            status_code=401,
            content=error_response(
                code="AUTH_REFRESH_TOKEN_EXPIRED",
                message="만료된 리프레시 토큰입니다.",
                retryable=False
            )
        )

    # 6. 사용자 조회
    user = (
        db.query(User)
        .filter(User.email == email)
        .first()
    )

    if not user:
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="USER_NOT_FOUND",
                message="사용자를 찾을 수 없습니다.",
                retryable=False
            )
        )

    # 7. Refresh Token의 사용자와 실제 사용자 확인
    if db_token.user_id != user.id:
        return JSONResponse(
            status_code=401,
            content=error_response(
                code="AUTH_TOKEN_USER_MISMATCH",
                message="토큰 사용자 정보가 일치하지 않습니다.",
                retryable=False
            )
        )

    # 8. 기존 Refresh Token 폐기
    db_token.is_revoked = True

    # 9. 새로운 Access Token 생성
    new_access_token = create_access_token(
        data={"sub": user.email}
    )

    # 10. 새로운 Refresh Token 생성
    new_refresh_token_value, new_jti = create_refresh_token(
        data={"sub": user.email}
    )

    # 11. 새로운 Refresh Token DB 저장
    new_db_token = RefreshToken(
        user_id=user.id,
        jti=new_jti,
        expires_at=(
            datetime.now(timezone.utc)
            + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        )
    )

    db.add(new_db_token)
    db.commit()

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token_value,
        "token_type": "bearer"
    }


# 4. 현재 로그인 사용자 조회
@router.get(
    "/users/me",
    response_model=UserResponse
)
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    # Access Token 검증
    payload = verify_token(token)

    if not payload:
        return JSONResponse(
            status_code=401,
            content=error_response(
                code="AUTH_INVALID_ACCESS_TOKEN",
                message="유효하지 않은 액세스 토큰입니다.",
                retryable=False
            )
        )

    # Access Token인지 확인
    if payload.get("type") != "access":
        return JSONResponse(
            status_code=401,
            content=error_response(
                code="AUTH_INVALID_TOKEN_TYPE",
                message="Access Token이 아닙니다.",
                retryable=False
            )
        )

    # 사용자 이메일
    email = payload.get("sub")

    if not email:
        return JSONResponse(
            status_code=401,
            content=error_response(
                code="AUTH_TOKEN_USER_MISSING",
                message="토큰에 사용자 정보가 없습니다.",
                retryable=False
            )
        )

    # 사용자 조회
    user = (
        db.query(User)
        .filter(User.email == email)
        .first()
    )

    if not user:
        return JSONResponse(
            status_code=401,
            content=error_response(
                code="USER_NOT_FOUND",
                message="사용자를 찾을 수 없습니다.",
                retryable=False
            )
        )

    return user


# 5. 로그아웃
@router.post("/auth/logout")
def logout(
    body: TokenRefreshRequest,
    db: Session = Depends(get_db)
):
    # Refresh Token 검증
    payload = verify_token(body.refresh_token)

    # 정상적인 Refresh Token인 경우
    if payload and payload.get("type") == "refresh":
        jti = payload.get("jti")

        if jti:
            # DB에서 해당 토큰 조회
            db_token = (
                db.query(RefreshToken)
                .filter(RefreshToken.jti == jti)
                .first()
            )

            if db_token:
                # Refresh Token 폐기
                db_token.is_revoked = True
                db.commit()

    return {
        "message": "로그아웃 되었습니다. 클라이언트 쪽에서 토큰을 삭제해주세요."
    }