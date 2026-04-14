import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config.postgres import DatabaseManager
from app.config.setting import settings
import app.model  # noqa: F401 — registers all ORM models

from app.router.user.auth.user import router as user_auth_router
from app.router.user.groups.groups import router as groups_router
from app.router.user.templates.templates import router as templates_router
from app.router.user.schedules.schedules import router as schedules_router
from app.router.user.whatsapp.whatsapp import router as whatsapp_router

from app.utils.helper import ResponseHelper

# ── Serverless detection ──────────────────────────────────────────────
# Vercel sets VERCEL=1 and AWS_LAMBDA_FUNCTION_NAME automatically.
# When running in serverless, skip Chrome/Scheduler (they need persistent processes).
IS_SERVERLESS = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

if not IS_SERVERLESS:
    from app.services.scheduler.wa_scheduler import WAScheduler
    from app.services.whatsapp.bot import WhatsAppBot

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting %s [%s]", settings.APP_NAME, settings.APP_ENV)
    await DatabaseManager.get_instance().init_db()
    logger.info("✅ Database tables ready")

    if not IS_SERVERLESS:
        # WhatsApp sessions are started on-demand (when user visits Link page or scheduler fires)
        WAScheduler.get_instance().start()
        logger.info("✅ Scheduler started")
    else:
        logger.info("⚡ Serverless mode — skipping scheduler & WhatsApp bot")

    yield

    if not IS_SERVERLESS:
        WAScheduler.get_instance().stop()
        WhatsAppBot.get_instance().close_all()   # gracefully quit all per-user Chrome instances
    logger.info("👋 Shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    description="WhatsApp group message scheduler for dieticians.",
    version="1.0.0",
    docs_url="/wa/v1/docs",
    redoc_url="/wa/v1/redoc",
    openapi_url="/wa/v1/openapi.json",
    lifespan=lifespan,
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    error_key, reason = ResponseHelper.extract_error_info(exc.detail)
    if error_key is None:
        error_key = ResponseHelper.error_key_for_status(exc.status_code)
    return JSONResponse(
        status_code=exc.status_code,
        content=ResponseHelper.error(key=error_key, reason=reason),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ResponseHelper.error(
            key="validation_error",
            data=jsonable_encoder(exc.errors()),
        ),
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://whatsapp-scheduler-backend-1hxh.onrender.com","http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_auth_router)
app.include_router(groups_router)
app.include_router(templates_router)
app.include_router(schedules_router)
app.include_router(whatsapp_router)


@app.get("/health", tags=["Health"])
async def health():
    return ResponseHelper.success(
        {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV},
        key="health_check_success",
    )


@app.get("/", tags=["Health"])
async def root():
    return ResponseHelper.success(
        {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV},
        key="health_check_success",
    )


@app.get("/keepalive", tags=["Health"])
async def keepalive():
    return ResponseHelper.success({"status": "alive"}, key="keepalive_success")

