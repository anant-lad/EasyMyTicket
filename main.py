"""
Main FastAPI application for Ticket Intake Classification System
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.ticket_routes import router as ticket_router
from routes.database_routes import router as database_router
from src.config import Config

app = FastAPI(
    title="Ticket Intake Classification API",
    description="An intelligent ticket classification system using LLM",
    version="1.0.0"
)

# Enable CORS for all routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(ticket_router, prefix="/api", tags=["tickets"])
app.include_router(database_router, prefix="/api", tags=["database"])


@app.on_event("startup")
async def startup_event():
    """Verify environment variables on startup"""
    try:
        Config.validate()
        print("✓ Configuration validated successfully")
    except ValueError as e:
        print(f"⚠ WARNING: {e}")


@app.get("/", tags=["root"])
async def root():
    """Root endpoint"""
    return {
        'message': 'Ticket Intake Classification API',
        'version': '1.0.0',
        'endpoints': {
            'tickets': {
                'create_ticket': 'POST /api/tickets/create',
                'get_all_tickets': 'GET /api/tickets',
                'get_ticket': 'GET /api/tickets/{ticket_number}',
            },
            'database': {
                'start_database': 'POST /api/database/start',
                'database_status': 'GET /api/database/status',
                'list_tables': 'GET /api/database/tables',
                'table_info': 'GET /api/database/tables/{table_name}',
                'table_data': 'GET /api/database/tables/{table_name}/data',
            },
            'system': {
                'health': 'GET /api/health',
                'docs': 'GET /docs',
                'redoc': 'GET /redoc'
            }
        }
    }


if __name__ == '__main__':
    import uvicorn
    
    try:
        Config.validate()
    except ValueError as e:
        print(f"WARNING: {e}")
        print("Please set it in your .env file")
    
    print(f"Starting Ticket Intake Classification API on {Config.HOST}:{Config.PORT}")
    print(f"API Documentation available at http://{Config.HOST}:{Config.PORT}/docs")
    
    uvicorn.run(
        "main:app",
        host=Config.HOST,
        port=Config.PORT,
        reload=Config.ENVIRONMENT == 'development'
    )
