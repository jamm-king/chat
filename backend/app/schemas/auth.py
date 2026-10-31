from pydantic import BaseModel, EmailStr
from fastapi.security import HTTPBearer

oauth2_scheme = HTTPBearer()

# 회원가입 요청
class UserCreate(BaseModel):
    email: EmailStr
    password: str

# 로그인 요청
class UserLogin(BaseModel):
    email: EmailStr
    password: str

# Access + Refresh Token 응답
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

# Refresh Token 요청
class TokenRefreshRequest(BaseModel):
    refresh_token: str

# 사용자 응답
class UserResponse(BaseModel):
    id: str
    email: str

    class Config:
        from_attributes = True