from datetime import datetime, timezone
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status
)
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
from datetime import timedelta
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Router
router = APIRouter(prefix="/api/v1",tags=["Auth"])

# Bearer Token 인증 객체
bearer_scheme = HTTPBearer()


# 1. 회원가입
@router.post("/auth/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
def signup(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    # 이메일 중복 확인
    existing_user = (
        db.query(User).filter(User.email == user_data.email).first())
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="이미 등록된 이메일입니다."
        )
    # 사용자 생성
    new_user = User(
        email=user_data.email,
        password_hash=hash_password(
            user_data.password
        ))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


# 2. 로그인
@router.post("/auth/login",
    response_model=TokenResponse
)
def login(
    user_data: UserLogin,
    db: Session = Depends(get_db)
):
    # 사용자 조회
    user = (
        db.query(User).filter(User.email == user_data.email).first()
    )
    # 사용자 존재 여부 + 비밀번호 확인
    if not user or not verify_password(user_data.password,user.password_hash):
        raise HTTPException(
            status_code=400,
            detail="이메일 또는 비밀번호가 올바르지 않습니다."
        )

    # Access Token 생성
    access_token = create_access_token(
        data={"sub": user.email})
    # Refresh Token 생성
    refresh_token_value, jti = create_refresh_token(
        data={"sub": user.email})
    # Refresh Token DB 저장
    db_token = RefreshToken(
        user_id=user.id,
        jti=jti,
        expires_at=(
            datetime.now(timezone.utc)
            + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)))
    db.add(db_token)
    db.commit()
    # 클라이언트에게 토큰 전달
    return {
        "access_token": access_token,
        "refresh_token": refresh_token_value,
        "token_type": "bearer"
    }

# 3. Refresh Token Rotation
@router.post("/auth/refresh",
    response_model=TokenResponse
)
def refresh_access_token(
    body: TokenRefreshRequest,
    db: Session = Depends(get_db)
):
    # 1. Refresh Token JWT 검증
    payload = verify_token(body.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="유효하지 않거나 만료된 리프레시 토큰입니다."
        )
    # 2. 토큰 타입 확인
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=401,
            detail="Refresh Token이 아닙니다."
        )
    # 3. JWT에서 정보 추출
    jti = payload.get("jti")
    email = payload.get("sub")
    if not jti or not email:
        raise HTTPException(
            status_code=401,
            detail="잘못된 리프레시 토큰입니다."
        )
    # 4. DB에서 Refresh Token 조회
    db_token = (
        db.query(RefreshToken).filter(RefreshToken.jti == jti).first()
    )
    # 5. DB 토큰 검증
    if not db_token:
        raise HTTPException(
            status_code=401,
            detail="등록되지 않은 리프레시 토큰입니다."
        )
    # 이미 사용된 Refresh Token인지 확인
    if db_token.is_revoked:
        raise HTTPException(
            status_code=401,
            detail="이미 폐기된 리프레시 토큰입니다."
        )
    # DB 기준 만료 여부 확인
    now = datetime.now(timezone.utc)
    expires_at = db_token.expires_at

    # DB에서 가져온 시간이 naive라면 UTC timezone을 지정
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < now:
        raise HTTPException(
            status_code=401,
            detail="만료된 리프레시 토큰입니다."
        )

    # 6. 사용자 조회
    user = (db.query(User).filter(User.email == email).first())
    if not user:
        raise HTTPException(
            status_code=404,
            detail="사용자를 찾을 수 없습니다."
        )
    # 7. Refresh Token의 사용자와 실제 사용자 확인
    if db_token.user_id != user.id:
        raise HTTPException(
            status_code=401,
            detail="토큰 사용자 정보가 일치하지 않습니다."
        )
    # 8. 기존 Refresh Token 폐기
    db_token.is_revoked = True
    # 9. 새로운 Access Token 생성
    new_access_token = create_access_token(data={"sub": user.email})
    # 10. 새로운 Refresh Token 생성
    new_refresh_token_value, new_jti = (
        create_refresh_token(
            data={"sub": user.email}))
    # 11. 새로운 Refresh Token DB 저장
    new_db_token = RefreshToken(
        user_id=user.id,
        jti=new_jti,
        expires_at=(
            datetime.now(timezone.utc)
            + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        ))
    db.add(new_db_token)
    db.commit()
    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token_value,
        "token_type": "bearer"
    }
    
# 4. 현재 로그인 사용자 조회
@router.get("/users/me",
    response_model=UserResponse
)
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
):
    token = credentials.credentials
    # Access Token 검증
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="유효하지 않은 액세스 토큰입니다."
        )
    # Access Token인지 확인
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=401,
            detail="Access Token이 아닙니다."
        )
    # 사용자 이메일
    email = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=401,
            detail="토큰에 사용자 정보가 없습니다."
        )
    # 사용자 조회
    user = (
        db.query(User).filter(User.email == email).first()
    )

    if not user:
        raise HTTPException(status_code=401,detail="사용자를 찾을 수 없습니다.")
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
                db.query(RefreshToken).filter(RefreshToken.jti == jti).first()
            )
            if db_token:
                # Refresh Token 폐기
                db_token.is_revoked = True
                db.commit()
            return {"message": "로그아웃 되었습니다. 클라이언트 쪽에서 토큰을 삭제해주세요."}

