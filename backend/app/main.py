from fastapi import FastAPI
from app.routers import auth

app = FastAPI(
    title="Chat AI RAG Service API",
    version="1.0",
    description="찿(Chat) 서비스 MVP 백엔드 API 서버"
)

# 인증 및 사용자 라우터 등록
app.include_router(auth.router)

# 추후 추가될 라우터 예시 (자료 관리, 대화 관리 등)
# from app.routers import resources, messages
# app.include_router(resources.router)
# app.include_router(messages.router)

@app.get("/")
def root():
    return {"message": "Chaj Backend Server is running successfully!"}