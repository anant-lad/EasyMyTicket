"""
Database management and exploration routes
"""
from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from enum import Enum
from src.database.db_connection import DatabaseConnection
from src.config import Config
from src.utils.database_restart import restart_and_fix_database
import subprocess
import os

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


class TechnicianCreate(BaseModel):
    """Model for creating a technician"""
    tech_id: str
    tech_name: str
    tech_mail: str
    tech_password: Optional[str] = None
    skills: Optional[str] = None


class UserCreate(BaseModel):
    """Model for creating a user"""
    user_id: str
    user_name: str
    user_mail: str
    user_password: Optional[str] = None


class GenericResponse(BaseModel):
    """Generic success/failure response"""
    success: bool
    message: str


class TechnicianAvailability(str, Enum):
    """Enumeration for technician availability"""
    available = "available"
    on_leave = "on_leave"
    half_day = "half_day"
    wfh = "wfh"
    offline = "offline"
    out_of_office = "out_of_office"
    away = "away"




class OAuthClientUpload(BaseModel):
    """Model for uploading OAuth client secret"""
    tech_id: str
    tech_mail: str
    client_secret_json: Dict[str, Any]


@router.post("/database/restart", response_model=DatabaseStatusResponse)
async def restart_database():
    """
    Restart the PostgreSQL database container and fix password if needed
    
    This route:
    1. Restarts the Docker container (stops and starts it)
    2. Attempts to update the password to match .env file if there's a mismatch
    3. Tests the database connection
    """
    try:
        success, message = restart_and_fix_database()
        
        if success:
            # Test database connection
            db_conn = get_db_connection()
            conn = db_conn.get_connection()
            
            # Test with a simple query
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            
            return DatabaseStatusResponse(
                status="success",
                message=f"Database restarted successfully. {message}",
                connected=True
            )
        else:
            return DatabaseStatusResponse(
                status="error",
                message=message,
                connected=False,
                error=message
            )
    except Exception as e:
        return DatabaseStatusResponse(
            status="error",
            message=f"Error restarting database: {str(e)}",
            connected=False,
            error=str(e)
        )


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


@router.get("/database/technicians", response_model=Dict[str, Any])
async def get_technicians(
    available: Optional[bool] = Query(None, description="Filter by availability"),
    skills: Optional[str] = Query(None, description="Search in skills (partial match)"),
    min_solved: Optional[int] = Query(None, description="Minimum solved tickets"),
    max_workload: Optional[int] = Query(None, description="Maximum current workload"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    Get technicians with detailed filtering
    """
    try:
        db_conn = get_db_connection()
        params = []
        where_clauses = []
        
        if available is not None:
            where_clauses.append("available = %s")
            params.append(available)
            
        if skills:
            where_clauses.append("skills ILIKE %s")
            params.append(f"%{skills}%")
            
        if min_solved is not None:
            where_clauses.append("solved_tickets >= %s")
            params.append(min_solved)
            
        if max_workload is not None:
            where_clauses.append("current_workload <= %s")
            params.append(max_workload)
            
        where_str = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        # Count query
        count_query = f"SELECT COUNT(*) as count FROM technician_data{where_str}"
        total_count = db_conn.execute_query(count_query, tuple(params))[0]['count']
        
        # Data query
        data_query = f"""
            SELECT * FROM technician_data 
            {where_str} 
            ORDER BY tech_id ASC 
            LIMIT %s OFFSET %s
        """
        data_params = params + [limit, offset]
        technicians = db_conn.execute_query(data_query, tuple(data_params))
        
        return {
            "success": True,
            "total": total_count,
            "returned": len(technicians),
            "data": technicians
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving technicians: {str(e)}"
        )


@router.get("/database/users", response_model=Dict[str, Any])
async def get_users(
    available: Optional[bool] = Query(None, description="Filter by availability"),
    min_raised: Optional[int] = Query(None, description="Minimum tickets raised"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    Get users with detailed filtering
    """
    try:
        db_conn = get_db_connection()
        params = []
        where_clauses = []
        
        if available is not None:
            where_clauses.append("available = %s")
            params.append(available)
            
        if min_raised is not None:
            where_clauses.append("no_tickets_raised >= %s")
            params.append(min_raised)
            
        where_str = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        # Count query
        count_query = f"SELECT COUNT(*) as count FROM user_data{where_str}"
        total_count = db_conn.execute_query(count_query, tuple(params))[0]['count']
        
        # Data query
        data_query = f"""
            SELECT * FROM user_data 
            {where_str} 
            ORDER BY user_id ASC 
            LIMIT %s OFFSET %s
        """
        data_params = params + [limit, offset]
        users = db_conn.execute_query(data_query, tuple(data_params))
        
        return {
            "success": True,
            "total": total_count,
            "returned": len(users),
            "data": users
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving users: {str(e)}"
        )


@router.post("/database/technicians", response_model=GenericResponse)
async def add_technicians(technicians: List[TechnicianCreate]):
    """
    Add multiple technicians to the database
    """
    try:
        db_conn = get_db_connection()
        count = 0
        
        for tech in technicians:
            query = """
                INSERT INTO technician_data (tech_id, tech_name, tech_mail, tech_password, skills)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tech_id) DO UPDATE SET
                    tech_name = EXCLUDED.tech_name,
                    tech_mail = EXCLUDED.tech_mail,
                    tech_password = EXCLUDED.tech_password,
                    skills = EXCLUDED.skills;
            """
            db_conn.execute_query(query, (
                tech.tech_id, 
                tech.tech_name, 
                tech.tech_mail, 
                tech.tech_password, 
                tech.skills
            ), fetch=False)
            count += 1
            
        return GenericResponse(
            success=True,
            message=f"Successfully items inserted/updated: {count} technicians"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error adding technicians: {str(e)}"
        )


@router.post("/database/users", response_model=GenericResponse)
async def add_users(users: List[UserCreate]):
    """
    Add multiple users to the database
    """
    try:
        db_conn = get_db_connection()
        count = 0
        
        for user in users:
            query = """
                INSERT INTO user_data (user_id, user_name, user_mail, user_password)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    user_name = EXCLUDED.user_name,
                    user_mail = EXCLUDED.user_mail,
                    user_password = EXCLUDED.user_password;
            """
            db_conn.execute_query(query, (
                user.user_id, 
                user.user_name, 
                user.user_mail, 
                user.user_password
            ), fetch=False)
            count += 1
            
        return GenericResponse(
            success=True,
            message=f"Successfully items inserted/updated: {count} users"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error adding users: {str(e)}"
        )


@router.delete("/database/tables/{table_name}/clear", response_model=GenericResponse)
async def clear_table(table_name: str = Path(..., description="Name of the table to clear")):
    """
    Clear all data from a specific table
    """
    try:
        db_conn = get_db_connection()
        
        # Verify table exists to prevent SQL injection
        check_query = "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s)"
        exists = db_conn.execute_query(check_query, (table_name,))[0]['exists']
        
        if not exists:
            raise HTTPException(status_code=404, detail=f"Table {table_name} not found")
            
        # Clear table
        clear_query = f'TRUNCATE TABLE "{table_name}" CASCADE'
        db_conn.execute_query(clear_query, fetch=False)
        
        return GenericResponse(
            success=True,
            message=f"Table {table_name} cleared successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error clearing table: {str(e)}"
        )

@router.patch("/database/technicians/{tech_id}/availability", response_model=GenericResponse)
async def update_technician_availability(
    tech_id: str = Path(..., description="The technician ID"),
    availability: TechnicianAvailability = Query(..., description="Select the technician availability")
):
    """
    Update technician availability using a dropdown selection
    """
    try:
        db_conn = get_db_connection()
        
        # Validation is now handled by Pydantic Enum
        new_val = availability.value
            
        query = "UPDATE technician_data SET availability = %s WHERE tech_id = %s"
        db_conn.execute_query(query, (new_val, tech_id), fetch=False)
        
        return GenericResponse(
            success=True,
            message=f"Availability for technician {tech_id} updated to {new_val}"
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=500,
            detail=f"Error updating status: {str(e)}"
        )


@router.post("/database/technicians/{tech_id}/oauth-client", response_model=GenericResponse)
async def upload_oauth_client(
    tech_id: str = Path(..., description="The technician ID"),
    upload_data: OAuthClientUpload = None
):
    """
    Upload OAuth client secret for a technician
    """
    try:
        from src.utils.oauth_manager import OAuthManager
        
        # Save the client secret file
        file_path = OAuthManager.save_client_secret(
            upload_data.tech_mail, 
            upload_data.client_secret_json
        )
        
        return GenericResponse(
            success=True,
            message=f"OAuth client secret saved for {upload_data.tech_mail} at {os.path.basename(file_path)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error saving OAuth client secret: {str(e)}"
        )


@router.get("/database/tickets/{ticket_number}/assignments", response_model=List[Dict[str, Any]])
async def get_ticket_assignments(
    ticket_number: str = Path(..., description="The ticket number")
):
    """
    Get assignment history for a specific ticket
    """
    try:
        from src.agents.smart_ticket_assignment import SmartAssignmentAgent
        agent = SmartAssignmentAgent(get_db_connection())
        history = agent.get_assignment_history(ticket_number)
        
        # Convert datetime objects
        from datetime import datetime
        for row in history:
            for key, value in row.items():
                if isinstance(value, datetime):
                    row[key] = value.isoformat()
                    
        return history
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving assignment history: {str(e)}"
        )
