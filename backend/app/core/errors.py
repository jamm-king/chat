from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


# 에러 응답 생성
def error_response(
    code: str,
    message: str,
    retryable: bool = False,
    details: list | None = None
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


# 애플리케이션 에러
# 라우터·의존성 어디서든 raise 하면 공통 에러 응답 형식으로 변환된다.
class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        details: list | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details


# HTTP 상태 코드별 에러 코드 / 메시지
HTTP_ERRORS = {
    status.HTTP_400_BAD_REQUEST: ("BAD_REQUEST", "잘못된 요청입니다."),
    status.HTTP_401_UNAUTHORIZED: ("UNAUTHORIZED", "인증이 필요합니다."),
    status.HTTP_403_FORBIDDEN: ("FORBIDDEN", "접근 권한이 없습니다."),
    status.HTTP_404_NOT_FOUND: ("NOT_FOUND", "요청한 리소스를 찾을 수 없습니다."),
    status.HTTP_405_METHOD_NOT_ALLOWED: ("METHOD_NOT_ALLOWED", "허용되지 않은 메서드입니다."),
}


# 요청 값 검증 실패 (422)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
):
    details = [
        {
            "field": ".".join(str(loc) for loc in err["loc"] if loc != "body"),
            "message": err["msg"]
        }
        for err in exc.errors()
    ]

    # Starlette 버전에 따라 422 상수 이름이 달라 숫자로 지정
    return JSONResponse(
        status_code=422,
        content=error_response(
            code="VALIDATION_ERROR",
            message="요청 값이 올바르지 않습니다.",
            retryable=False,
            details=details
        )
    )


# HTTP 에러 (404, 405 등)
async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException
):
    code, message = HTTP_ERRORS.get(
        exc.status_code,
        (f"HTTP_{exc.status_code}", "요청을 처리할 수 없습니다.")
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            code=code,
            message=message,
            retryable=False
        ),
        headers=getattr(exc, "headers", None)
    )


# 애플리케이션 에러 (AppError)
async def app_error_handler(
    request: Request,
    exc: AppError
):
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details
        )
    )


# 처리되지 않은 서버 에러 (500)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception
):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response(
            code="INTERNAL_SERVER_ERROR",
            message="서버 내부 오류가 발생했습니다.",
            retryable=True
        )
    )


# 공통 에러 핸들러 등록
def register_exception_handlers(app: FastAPI):
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
