"""FastAPI Main Application Entry Point for DrugTime API."""
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.schemas.common import ErrorEnvelope, ErrorDetail
from app.mock_db import db
from app.routers import (
    auth, consents, conditions, prescriptions,
    schedules, safety, caregivers, meals, admin, disease_groups
)

app = FastAPI(
    title="DrugTime API",
    version="1.0.0",
    description="Backend API Gateway & Contract-First Specification for DrugTime (Mobile App & Admin Web)",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Standardized Error Handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code = "HTTP_ERROR"
    message = str(exc.detail)
    details = None
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", "HTTP_ERROR")
        message = exc.detail.get("message", "Đã xảy ra lỗi")
        details = exc.detail.get("details")

    error_response = ErrorEnvelope(
        error=ErrorDetail(code=code, message=message, details=details)
    )
    return JSONResponse(status_code=exc.status_code, content=error_response.model_dump())

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = []
    for err in exc.errors():
        field = ".".join([str(loc) for loc in err["loc"] if loc != "body"])
        details.append({"field": field or "body", "issue": err["msg"]})

    error_response = ErrorEnvelope(
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message="Dữ liệu đầu vào không hợp lệ",
            details=details
        )
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=error_response.model_dump())

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    error_response = ErrorEnvelope(
        error=ErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message=f"Lỗi hệ thống nội bộ: {str(exc)}",
            details=None
        )
    )
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=error_response.model_dump())

# Health check
@app.get("/healthz", tags=["Hạ tầng"])
def health_check():
    return {
        "status": "ok",
        "service": "drugtime-api",
        "version": "1.0.0",
        "workers": db.worker_heartbeats
    }

# Mount All 10 Domain Routers
API_V1_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_V1_PREFIX)
app.include_router(consents.router, prefix=API_V1_PREFIX)
app.include_router(conditions.router, prefix=API_V1_PREFIX)
app.include_router(prescriptions.router, prefix=API_V1_PREFIX)
app.include_router(schedules.router, prefix=API_V1_PREFIX)
app.include_router(safety.router, prefix=API_V1_PREFIX)
app.include_router(caregivers.router, prefix=API_V1_PREFIX)
app.include_router(meals.router, prefix=API_V1_PREFIX)
app.include_router(admin.router, prefix=API_V1_PREFIX)
app.include_router(disease_groups.router, prefix=API_V1_PREFIX)
