"""
Main FastAPI application for Ticket Intake Classification System
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.ticket_routes import router as ticket_router
from routes.database_routes import router as database_router
from src.config import Config
from src.utils.database_startup import ensure_database_running, wait_for_database_ready
from src.utils.database_restart import restart_and_fix_database

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
    """Verify environment variables and ensure database is running on startup"""
    try:
        Config.validate()
        print("✓ Configuration validated successfully")
    except ValueError as e:
        print(f"⚠ WARNING: {e}")
    
    # Automatically start database if not running
    print("\n" + "="*80)
    print("🔍 Checking database status...")
    print("="*80)
    
    try:
        success, message = ensure_database_running()
        
        if success:
            print(message)
            # Wait for database to be ready
            print("⏳ Waiting for database to be ready...")
            if wait_for_database_ready():
                print("✓ Database is ready and accepting connections")
            else:
                print("⚠ Database container is running but not ready yet. It may take a few more seconds.")
        else:
            print(f"❌ {message}")
            print("\n" + "="*80)
            print("⚠️  DATABASE SETUP ISSUE DETECTED")
            print("="*80)
            if "password authentication failed" in message.lower() or "password" in message.lower():
                print("\nThe database container exists but the password doesn't match.")
                print("Attempting to restart and fix the database...\n")
                
                # Try to restart and fix
                restart_success, restart_message = restart_and_fix_database()
                if restart_success:
                    print(f"✓ {restart_message}")
                    # Verify it works now
                    if wait_for_database_ready():
                        print("✓ Database is ready and accepting connections")
                else:
                    print(f"❌ {restart_message}")
                    print("\nManual fix options:\n")
                    print("Option 1: Update .env to match existing container")
                    print("  - Check what password was used when creating the container")
                    print("  - Update DB_PASSWORD in your .env file to match\n")
                    print("Option 2: Manually update password in container")
                    print("  - Run: docker exec -it Autotask psql -U postgres")
                    print(f"  - Then run: ALTER USER {Config.DB_USER} WITH PASSWORD '{Config.DB_PASSWORD}';")
            else:
                print("\nPlease check the error message above and fix the issue.")
                print("You may need to start the database manually using: ./start_database.sh")
            print("="*80)
    except Exception as e:
        print(f"❌ Error checking/starting database: {e}")
        import traceback
        traceback.print_exc()
        print("\n⚠ You may need to start the database manually using: ./start_database.sh")
    
    print("="*80 + "\n")


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
                'restart_database': 'POST /api/database/restart',
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
