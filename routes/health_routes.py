"""
System Health routes
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
import psutil
import platform
import time
from src.database.db_connection import DatabaseConnection

router = APIRouter()

# Lazy loading for database connection
_db_conn = None

def get_db_connection():
    """Get or create database connection (lazy loading)"""
    global _db_conn
    if _db_conn is None:
        _db_conn = DatabaseConnection()
    return _db_conn


@router.get("/system/health")
async def get_system_health():
    """
    Get comprehensive system health metrics
    """
    try:
        db_conn = get_db_connection()
        
        # Database Health
        db_status = "unknown"
        db_latency = 0
        active_connections = 0
        try:
            start_time = time.time()
            # Simple query to check connectivity
            db_conn.execute_query("SELECT 1")
            db_latency = (time.time() - start_time) * 1000  # ms
            db_status = "healthy"
            
            # Get active connections
            conn_query = "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
            conn_result = db_conn.execute_query(conn_query)
            if conn_result:
                active_connections = conn_result[0]['count']
                
        except Exception as e:
            db_status = f"unhealthy: {str(e)}"

        # System Resources
        cpu_usage = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "services": {
                "database": {
                    "status": db_status,
                    "latency_ms": round(db_latency, 2),
                    "active_connections": active_connections
                },
                "api": {
                    "status": "healthy",
                    "uptime": "unknown" # Could implement uptime tracking
                }
            },
            "resources": {
                "cpu": {
                    "usage_percent": cpu_usage,
                    "cores": psutil.cpu_count()
                },
                "memory": {
                    "total_gb": round(memory.total / (1024**3), 2),
                    "used_gb": round(memory.used / (1024**3), 2),
                    "percent": memory.percent
                },
                "disk": {
                    "total_gb": round(disk.total / (1024**3), 2),
                    "used_gb": round(disk.used / (1024**3), 2),
                    "percent": disk.percent
                }
            },
            "system": {
                "os": platform.system(),
                "release": platform.release(),
                "python_version": platform.python_version()
            }
        }
        
    except Exception as e:
        print(f"Error fetching system health: {e}")
        raise HTTPException(status_code=500, detail=str(e))
