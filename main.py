"""
EasyMyTicket — FastAPI application entry point.
Cloud-native version: no Docker management, structured logging, K8s health probes, API auth.
"""
import logging
import os

# Set by startup_event() once DB is confirmed reachable. The readiness probe
# checks this flag instead of probing the pool on every call — avoids transient
# pool exhaustion causing false "not ready" during normal operation.
_APP_READY = False

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import Config
from src.utils.logger import setup_logging
from src.middleware.auth import APIKeyMiddleware
from routes.ticket_routes import router as ticket_router
from routes.database_routes import router as database_router
from routes.technician_routes import router as technician_router
from routes.agent_routes import router as agent_router
from routes.trace_routes import router as trace_router
from routes.monitoring_routes import router as monitoring_router
from routes.chat_routes import router as chat_router
from routes.auth_routes import router as auth_router
from routes.admin_routes import router as admin_router

# Logging must be configured before any other module logs
setup_logging()
log = logging.getLogger(__name__)

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="EasyMyTicket API",
    description="AI-powered support ticketing platform",
    version="2.0.0",
)

# Auth middleware (checks X-API-Key header; skips health/docs paths)
app.add_middleware(APIKeyMiddleware)

_dev_origins = ["http://localhost:3000", "http://localhost:3001"]
_default_prod_origins = (
    "https://easymyticket.vercel.app,"
    "https://easymyticket-frontend.vercel.app"
)
_prod_origins = os.getenv("ALLOWED_ORIGINS", _default_prod_origins).split(",")
# Strip whitespace from each origin in case of formatting issues
_prod_origins = [o.strip() for o in _prod_origins if o.strip()]
_allowed_origins = _dev_origins if Config.ENVIRONMENT not in ("production", "prod") else _prod_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(ticket_router,     prefix="/api", tags=["tickets"])
app.include_router(database_router,   prefix="/api", tags=["database"])
app.include_router(technician_router, prefix="/api", tags=["technician"])
app.include_router(agent_router,      tags=["agent"])
app.include_router(trace_router,      prefix="/api", tags=["observability"])
app.include_router(monitoring_router, tags=["monitoring"])
app.include_router(chat_router,       tags=["chat"])

# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    global _APP_READY
    import asyncio
    import routes.agent_routes as _ar
    _ar._main_loop = asyncio.get_running_loop()

    try:
        Config.validate()
        log.info("Configuration validated")
    except ValueError as e:
        log.warning("Configuration warning: %s", e)

    # Apply idempotent schema migrations (E1-E5 new tables/columns)
    from src.database.migrations import run_migrations
    run_migrations()

    from src.utils.database_startup import wait_for_database_ready
    log.info("Waiting for database at %s:%s ...", Config.DB_HOST, Config.DB_PORT)
    if wait_for_database_ready():
        log.info("Database ready")
        _APP_READY = True
    else:
        log.warning("Database not ready — requests may fail until it becomes available")
        _APP_READY = True  # Allow traffic anyway; DB errors surface per-request

# ── K8s health probes ─────────────────────────────────────────────────────────

@app.get("/healthz", tags=["system"], include_in_schema=False)
async def liveness():
    """Kubernetes liveness probe — always returns 200 if process is alive."""
    return {"status": "alive"}


@app.get("/readyz", tags=["system"], include_in_schema=False)
async def readiness():
    """Kubernetes readiness probe — returns 200 once startup_event() has completed."""
    if _APP_READY:
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "not ready", "reason": "startup in progress"})

# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/", tags=["root"])
async def root():
    return {
        "service": "EasyMyTicket API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health",
        "endpoints": {
            "tickets": {
                "create":  "POST /api/tickets/create",
                "list":    "GET  /api/tickets",
                "get":     "GET  /api/tickets/{ticket_number}",
                "resolve": "PATCH /api/tickets/{ticket_number}/resolve",
            },
            "technician": {
                "assist": "POST /api/technician/assist",
            },
        },
    }


if __name__ == "__main__":
    import uvicorn
    log.info("Starting on %s:%s", Config.HOST, Config.PORT)
    uvicorn.run(
        "main:app",
        host=Config.HOST,
        port=Config.PORT,
        reload=Config.ENVIRONMENT == "development",
        workers=1,  # must stay 1: _connected_agents and _pending_approvals are in-process dicts
    )
