"""
Database management and exploration routes
"""
from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from src.database.db_connection import DatabaseConnection
from src.config import Config
import subprocess

router = APIRouter()

# Initialize database connection (will be lazy-loaded)
_db_conn = None

def get_db_connection():
    """Get or create database connection"""
    global _db_conn
    if _db_conn is None:
        _db_conn = DatabaseConnection()
    return _db_conn


# Response models
class DatabaseStatusResponse(BaseModel):
    """Response model for database status"""
    status: str
    message: str
    connected: bool
    error: Optional[str] = None


class TableListResponse(BaseModel):
    """Response model for table list"""
    success: bool
    tables: List[Dict[str, Any]]
    count: int


class TableInfoResponse(BaseModel):
    """Response model for table information"""
    success: bool
    table_name: str
    columns: List[Dict[str, Any]]
    row_count: int
    sample_data: Optional[List[Dict[str, Any]]] = None


class TableDataResponse(BaseModel):
    """Response model for table data"""
    success: bool
    table_name: str
    total_rows: int
    returned_rows: int
    columns: List[str]
    data: List[Dict[str, Any]]


@router.post("/database/start", response_model=DatabaseStatusResponse)
async def start_database():
    """
    Start the PostgreSQL database container and establish connection
    
    This route:
    1. Checks if the Docker container is running
    2. Starts it if not running
    3. Tests the database connection
    """
    try:
        # Check if container exists and is running
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=Autotask", "--format", "{{.Names}}|{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        container_info = result.stdout.strip()
        
        if not container_info:
            return DatabaseStatusResponse(
                status="error",
                message="Autotask container not found. Please create it first using the start_database.sh script.",
                connected=False,
                error="Container not found"
            )
        
        container_name, status = container_info.split("|", 1)
        
        if "Up" not in status:
            # Container exists but is not running, start it
            print(f"Starting container {container_name}...")
            start_result = subprocess.run(
                ["docker", "start", container_name],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if start_result.returncode != 0:
                return DatabaseStatusResponse(
                    status="error",
                    message=f"Failed to start container: {start_result.stderr}",
                    connected=False,
                    error=start_result.stderr
                )
            
            # Wait a bit for PostgreSQL to be ready
            import time
            time.sleep(3)
        
        # Test database connection
        db_conn = get_db_connection()
        conn = db_conn.get_connection()
        
        # Test with a simple query
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        
        return DatabaseStatusResponse(
            status="success",
            message="Database is running and connected successfully",
            connected=True
        )
        
    except subprocess.TimeoutExpired:
        return DatabaseStatusResponse(
            status="error",
            message="Timeout while checking/starting database container",
            connected=False,
            error="Timeout"
        )
    except Exception as e:
        return DatabaseStatusResponse(
            status="error",
            message=f"Error starting database: {str(e)}",
            connected=False,
            error=str(e)
        )


@router.get("/database/tables", response_model=TableListResponse)
async def list_tables():
    """
    Get list of all tables in the database
    
    Returns:
        List of all tables with their row counts
    """
    try:
        db_conn = get_db_connection()
        
        query = """
            SELECT 
                table_name,
                (SELECT COUNT(*) 
                 FROM information_schema.columns 
                 WHERE table_name = t.table_name) as column_count
            FROM information_schema.tables t
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """
        
        tables = db_conn.execute_query(query)
        
        # Get row count for each table
        table_list = []
        for table in tables:
            table_name = table['table_name']
            try:
                count_query = f'SELECT COUNT(*) as count FROM "{table_name}"'
                count_result = db_conn.execute_query(count_query)
                row_count = count_result[0]['count'] if count_result else 0
            except:
                row_count = 0
            
            table_list.append({
                "table_name": table_name,
                "column_count": table['column_count'],
                "row_count": row_count
            })
        
        return TableListResponse(
            success=True,
            tables=table_list,
            count=len(table_list)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error listing tables: {str(e)}"
        )


@router.get("/database/tables/{table_name}", response_model=TableInfoResponse)
async def get_table_info(
    table_name: str = Path(..., description="Name of the table to inspect"),
    include_sample: bool = Query(True, description="Include sample data (first 5 rows)")
):
    """
    Get detailed information about a specific table
    
    Args:
        table_name: Name of the table
        include_sample: Whether to include sample data
    
    Returns:
        Table structure, column information, and optionally sample data
    """
    try:
        db_conn = get_db_connection()
        
        # Get column information
        column_query = """
            SELECT 
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' 
            AND table_name = %s
            ORDER BY ordinal_position;
        """
        
        columns = db_conn.execute_query(column_query, (table_name,))
        
        if not columns:
            raise HTTPException(
                status_code=404,
                detail=f"Table '{table_name}' not found"
            )
        
        # Get row count
        count_query = f'SELECT COUNT(*) as count FROM "{table_name}"'
        count_result = db_conn.execute_query(count_query)
        row_count = count_result[0]['count'] if count_result else 0
        
        # Get sample data if requested
        sample_data = None
        if include_sample and row_count > 0:
            sample_query = f'SELECT * FROM "{table_name}" LIMIT 5'
            sample_data = db_conn.execute_query(sample_query)
        
        # Format column information
        column_info = []
        for col in columns:
            col_info = {
                "name": col['column_name'],
                "type": col['data_type'],
                "nullable": col['is_nullable'] == 'YES',
                "default": col['column_default']
            }
            if col['character_maximum_length']:
                col_info["max_length"] = col['character_maximum_length']
            column_info.append(col_info)
        
        return TableInfoResponse(
            success=True,
            table_name=table_name,
            columns=column_info,
            row_count=row_count,
            sample_data=sample_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting table info: {str(e)}"
        )


@router.get("/database/tables/{table_name}/data", response_model=TableDataResponse)
async def get_table_data(
    table_name: str = Path(..., description="Name of the table"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum number of rows to return"),
    offset: int = Query(0, ge=0, description="Number of rows to skip"),
    order_by: Optional[str] = Query(None, description="Column to order by (default: first column)")
):
    """
    Get data from a specific table with pagination
    
    Args:
        table_name: Name of the table
        limit: Maximum number of rows to return (1-1000)
        offset: Number of rows to skip (for pagination)
        order_by: Column name to order by (optional)
    
    Returns:
        Table data with pagination information
    """
    try:
        db_conn = get_db_connection()
        
        # Verify table exists
        table_check = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = %s
        """
        table_exists = db_conn.execute_query(table_check, (table_name,))
        
        if not table_exists:
            raise HTTPException(
                status_code=404,
                detail=f"Table '{table_name}' not found"
            )
        
        # Get total row count
        count_query = f'SELECT COUNT(*) as count FROM "{table_name}"'
        count_result = db_conn.execute_query(count_query)
        total_rows = count_result[0]['count'] if count_result else 0
        
        # Get column names
        column_query = """
            SELECT column_name 
            FROM information_schema.columns
            WHERE table_schema = 'public' 
            AND table_name = %s
            ORDER BY ordinal_position
        """
        columns_result = db_conn.execute_query(column_query, (table_name,))
        columns = [col['column_name'] for col in columns_result]
        
        # Build query with ordering
        if order_by and order_by in columns:
            order_clause = f'ORDER BY "{order_by}" DESC'
        elif columns:
            # Default to first column descending
            order_clause = f'ORDER BY "{columns[0]}" DESC'
        else:
            order_clause = ""
        
        # Get data
        data_query = f'SELECT * FROM "{table_name}" {order_clause} LIMIT %s OFFSET %s'
        data = db_conn.execute_query(data_query, (limit, offset))
        
        # Convert datetime objects to strings for JSON serialization
        from datetime import datetime
        for row in data:
            for key, value in row.items():
                if isinstance(value, datetime):
                    row[key] = value.isoformat()
        
        return TableDataResponse(
            success=True,
            table_name=table_name,
            total_rows=total_rows,
            returned_rows=len(data),
            columns=columns,
            data=data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting table data: {str(e)}"
        )


@router.get("/database/status", response_model=DatabaseStatusResponse)
async def get_database_status():
    """
    Get current database connection status
    
    Returns:
        Database connection status and information
    """
    try:
        db_conn = get_db_connection()
        conn = db_conn.get_connection()
        
        # Test connection with a simple query
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
        
        return DatabaseStatusResponse(
            status="success",
            message=f"Database connected successfully. PostgreSQL version: {version.split(',')[0]}",
            connected=True
        )
        
    except Exception as e:
        return DatabaseStatusResponse(
            status="error",
            message=f"Database connection failed: {str(e)}",
            connected=False,
            error=str(e)
        )

