"""
Audit Log routes
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, Any, Optional, List
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


class AuditLogResponse(BaseModel):
    """Response model for audit logs list"""
    success: bool
    logs: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int
    has_more: bool


@router.get("/audit-logs", response_model=AuditLogResponse)
async def get_audit_logs(
    limit: int = Query(50, ge=1, le=1000, description="Maximum number of logs to return"),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type")
):
    """
    Get audit logs with pagination and filtering
    """
    try:
        db_conn = get_db_connection()
        
        # Build query
        where_conditions = []
        params = []
        
        if user_id:
            where_conditions.append("user_id = %s")
            params.append(user_id)
        
        if action:
            where_conditions.append("action = %s")
            params.append(action)
            
        if resource_type:
            where_conditions.append("resource_type = %s")
            params.append(resource_type)
            
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        # Get total count
        count_query = f"SELECT COUNT(*) FROM audit_logs WHERE {where_clause}"
        count_result = db_conn.execute_query(count_query, tuple(params))
        total = count_result[0]['count'] if count_result else 0
        
        # Get logs
        query = f"""
            SELECT * FROM audit_logs 
            WHERE {where_clause} 
            ORDER BY timestamp DESC 
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        
        logs = db_conn.execute_query(query, tuple(params))
        
        # Convert datetimes
        if logs:
            for log in logs:
                if isinstance(log['timestamp'], datetime):
                    log['timestamp'] = log['timestamp'].isoformat()
        
        return AuditLogResponse(
            success=True,
            logs=logs or [],
            total=total,
            limit=limit,
            offset=offset,
            has_more=(offset + limit) < total
        )
        
    except Exception as e:
        print(f"Error fetching audit logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
