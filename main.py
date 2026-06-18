"""
EasyMyTicket — FastAPI application entry point.
Cloud-native version: no Docker management, structured logging, K8s health probes, API auth.
"""
import logging

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in prod via ALLOWED_ORIGINS env var
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    else:
        log.warning("Database not ready — requests may fail until it becomes available")

# ── K8s health probes ─────────────────────────────────────────────────────────

@app.get("/healthz", tags=["system"], include_in_schema=False)
async def liveness():
    """Kubernetes liveness probe — always returns 200 if process is alive."""
    return {"status": "alive"}


@app.get("/readyz", tags=["system"], include_in_schema=False)
async def readiness():
    """Kubernetes readiness probe — returns 200 only when DB is reachable."""
    try:
        from src.database.db_connection import _get_pool
        pool = _get_pool()
        conn = pool.getconn()
        pool.putconn(conn)
        return {"status": "ready"}
    except Exception as e:
        log.warning("Readiness check failed: %s", e)
        return JSONResponse(status_code=503, content={"status": "not ready", "reason": str(e)})

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
        workers=1 if Config.ENVIRONMENT == "development" else 2,
    )
