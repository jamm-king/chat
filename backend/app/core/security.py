import os
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from jose import jwt, JWTError
from passlib.context import CryptContext


# .env 파일에서 환경 변수 로드
load_dotenv()

# JWT Secret Key
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "your-super-secret-key-change-it"
)
if not SECRET_KEY:
    raise ValueError("SECRET_KEY 환경 변수가 설정되지 않았습니다!")


# JWT 알고리즘
ALGORITHM = "HS256"

# Access Token 만료 시간
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Refresh Token 만료 시간
REFRESH_TOKEN_EXPIRE_DAYS = 1


# 비밀번호 암호화
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

# 비밀번호 관련
def hash_password(password: str) -> str:
    """비밀번호를 bcrypt로 해시화"""
    return pwd_context.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str
) -> bool:
    """입력한 비밀번호와 해시 비밀번호 비교"""
    return pwd_context.verify(
        plain_password,
        hashed_password
    )


# Access Token
def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None
) -> str:
    """Access Token 생성"""
    to_encode = data.copy()
    expire = (
        datetime.now(timezone.utc)
        + (
            expires_delta
            or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
    )
    to_encode.update({
        "exp": expire,
        "type": "access"
    })
    return jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )


# Refresh Token
def create_refresh_token(
    data: dict,
    expires_delta: timedelta | None = None
) -> tuple[str, str]:
    """
    Refresh Token 생성
    return:
        token : JWT Refresh Token
        jti   : Refresh Token 고유 ID
    """
    to_encode = data.copy()
    # Refresh Token마다 새로운 고유 ID 생성
    jti = str(uuid.uuid4())
    expire = (
        datetime.now(timezone.utc)
        + (
            expires_delta
            or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        )
    )
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "jti": jti
    })
    token = jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )
    return token, jti


# Token 검증
def verify_token(token: str) -> dict | None:
    """JWT 토큰 검증"""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )
        return payload
    except JWTError:
        return None