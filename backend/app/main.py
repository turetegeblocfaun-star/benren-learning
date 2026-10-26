from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import router as api_v1_router
from app.core.config import get_settings
from app.core.errors import ApiError, ErrorBody, ErrorEnvelope, api_error_handler
from app.core.ids import new_id
from app.core.logging import configure_logging
from app.core.security import origin_is_trusted
from app.services.storage import build_storage

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="“笨”人学习 API",
        version="0.3.0-stage3-prd-complete",
        description="第三阶段：补齐 PRD P0/P1/P2 的全部后端合同与治理闭环。",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "X-Confirmation-Token",
        ],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: object) -> object:
        request.state.request_id = new_id("req")
        unsafe_method = request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        has_session_cookie = bool(request.cookies.get(settings.session_cookie_name))
        if (
            settings.csrf_origin_protection
            and settings.app_env != "test"
            and unsafe_method
            and has_session_cookie
        ):
            trusted_origins = [
                settings.app_base_url,
                *settings.cors_origins,
                *settings.csrf_trusted_origins,
            ]
            if not origin_is_trusted(request.headers.get("Origin"), trusted_origins):
                body = ErrorEnvelope(
                    error=ErrorBody(
                        code="CSRF_ORIGIN_DENIED",
                        message="请求来源无法验证，请从正式页面重新操作。",
                        request_id=request.state.request_id,
                    )
                )
                return JSONResponse(status_code=403, content=body.model_dump(mode="json"))
        response = await call_next(request)  # type: ignore[operator]
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = {
            "fields": [
                {"path": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
                for error in exc.errors()[:20]
            ]
        }
        body = ErrorEnvelope(
            error=ErrorBody(
                code="INVALID_INPUT",
                message="请求内容格式不正确，请检查后重试。",
                request_id=request.state.request_id,
                details=details,
            )
        )
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled request error",
            extra={"event_data": {"request_id": request.state.request_id}},
        )
        body = ErrorEnvelope(
            error=ErrorBody(
                code="INTERNAL_ERROR",
                message="服务暂时出现问题，请稍后重试。",
                request_id=request.state.request_id,
            )
        )
        return JSONResponse(status_code=500, content=body.model_dump(mode="json"))

    @app.on_event("startup")
    def startup() -> None:
        settings.validate_runtime_secrets()
        build_storage(settings)

    app.include_router(api_v1_router)
    return app


app = create_app()
