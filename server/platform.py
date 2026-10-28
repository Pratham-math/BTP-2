"""Production platform entry point. Legacy single-owner routes are not mounted."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from server.auth import SupabaseVerifier
from server.assessment.runner import configured_runner
from server.config import PROJECT_DIR
from server.database import Profile, make_engine, session_factory
from server.object_store import ObjectStore
from server.platform_settings import PlatformSettings
from server.http_limits import BodyLimit, UserLimiter
from server.logging_safety import configure_safe_logs
from server.providers.base import GenerationError


def create_app(settings=None, *, engine=None, verify_token=None, objects=None, runner=None):
    configure_safe_logs()
    settings = settings or PlatformSettings.from_env()
    engine = engine or (make_engine(settings.database_url) if settings.database_url else None)
    @asynccontextmanager
    async def lifespan(app):
        yield
        app.state.runner.close()
        if engine:
            engine.dispose()

    app = FastAPI(title="Tinker Teaching Platform", version="3.0.0", lifespan=lifespan)
    app.state.settings, app.state.engine = settings, engine
    app.state.db = session_factory(engine) if engine else None
    if settings.local:
        from server.local_services import LocalObjectStore, verify_local_token
        verify_token, objects = verify_token or verify_local_token, objects or LocalObjectStore()
    app.state.verify_token = verify_token or SupabaseVerifier(settings)
    app.state.objects = objects or ObjectStore(settings)
    app.state.runner = runner or configured_runner(settings)
    app.state.limiter = UserLimiter()
    app.add_middleware(BodyLimit, max_upload=settings.max_upload_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.origins), allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"],
                       expose_headers=["Content-Range", "Accept-Ranges"])

    @app.middleware("http")
    async def headers(request: Request, call_next):
        if settings.demo_runner and (not request.client or request.client.host not in {"127.0.0.1", "::1"}):
            return JSONResponse({"detail": "Local-demo Python is available only from this laptop's loopback address."}, status_code=403)
        # Cross-origin reads of authenticated data are governed by CORS. State
        # changes also reject unexpected browser origins explicitly.
        origin = request.headers.get("origin")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin and origin not in settings.origins:
            return JSONResponse({"detail": "This application origin is not allowed."}, status_code=403)
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > settings.max_upload_bytes + 1024 * 1024:
                    return JSONResponse({"detail": "The request exceeds the upload limit."}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid request size."}, status_code=400)
        response = await call_next(request)
        response.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin",
                                 "X-Frame-Options": "DENY", "Permissions-Policy": "camera=(), microphone=()"})
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation(request, error):
        return JSONResponse({"detail": [{"loc": x["loc"], "msg": x["msg"]} for x in error.errors()]}, status_code=422)

    @app.exception_handler(GenerationError)
    async def generation_error(request, error):
        return JSONResponse({"detail": {"code": error.code, "message": str(error)}}, status_code=503)

    @app.exception_handler(StaleDataError)
    async def stale_error(request, error):
        return JSONResponse({"detail": "This record changed in another tab. Reload before saving."}, status_code=409)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, error):
        return JSONResponse({"detail": "This request conflicts with saved data. Reload and retry."}, status_code=409)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        return JSONResponse({"detail": "The database is temporarily unavailable. Your last confirmed progress is saved."}, status_code=503)

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "tinker-platform"}

    @app.get("/api/ready")
    def readiness():
        checks = settings.checks()
        if engine:
            try:
                with engine.connect() as connection:
                    connection.execute(select(Profile.id).limit(1))
            except SQLAlchemyError:
                checks["database"] = False
        return JSONResponse({"ready": all(checks.values()), "checks": checks,
                             "runner_mode": "local_demo" if settings.demo_runner else "judge0",
                             "runner_isolated": not settings.demo_runner and checks["python_runner"],
                             "scope": "configuration-and-database-only; not release acceptance"}, status_code=200 if all(checks.values()) else 503)

    @app.get("/api/config")
    def config():
        return {"auth_mode": "local" if settings.local else "supabase", "supabase_url": settings.supabase_url, "supabase_publishable_key": settings.supabase_public_key,
                "auth_configured": bool(settings.supabase_url and settings.supabase_public_key),
                "google_oauth_verified": settings.google_oauth_verified,
                "source_features": settings.source_features(),
                "setup_required": [key for key, ready in settings.checks().items() if not ready],
                "python_enabled": settings.checks()["python_runner"],
                "runner_mode": "local_demo" if settings.demo_runner else "judge0",
                "runner_isolated": not settings.demo_runner and settings.checks()["python_runner"]}

    from server.platform_api import router as resources
    from server import erasure  # Register account/maintenance routes before inclusion.
    from server.learning.api import router as learning
    from server.lessons.editing import router as editing
    if settings.local:
        from server.local_api import router as local_routes
        app.include_router(local_routes)
    app.include_router(resources)
    app.include_router(learning)
    app.include_router(editing)

    frontend = PROJECT_DIR / "client" / "dist"
    if frontend.exists():
        if (frontend / "assets").exists():
            app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")
        @app.get("/{path:path}")
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "API route not found."}, status_code=404)
            return FileResponse(frontend / "index.html")
    return app


app = create_app()
