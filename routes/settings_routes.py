"""
System Settings routes
"""
from fastapi import APIRouter, HTTPException
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


class SettingUpdate(BaseModel):
    """Request model for updating a setting"""
    value: Any
    updated_by: str


class SettingsResponse(BaseModel):
    """Response model for settings"""
    success: bool
    settings: Dict[str, Any]


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """
    Get all system settings
    """
    try:
        db_conn = get_db_connection()
        
        query = "SELECT setting_key, setting_value, description FROM system_settings"
        results = db_conn.execute_query(query)
        
        settings = {}
        if results:
            for row in results:
                settings[row['setting_key']] = row['setting_value']
                
        return SettingsResponse(
            success=True,
            settings=settings
        )
        
    except Exception as e:
        print(f"Error fetching settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/settings/{key}")
async def update_setting(key: str, update: SettingUpdate):
    """
    Update a system setting
    """
    try:
        db_conn = get_db_connection()
        
        # Check if setting exists
        check_query = "SELECT setting_key FROM system_settings WHERE setting_key = %s"
        exists = db_conn.execute_query(check_query, (key,))
        
        import json
        value_json = json.dumps(update.value)
        
        if exists:
            query = """
                UPDATE system_settings 
                SET setting_value = %s, updated_by = %s, updated_at = CURRENT_TIMESTAMP 
                WHERE setting_key = %s
            """
            db_conn.execute_query(query, (value_json, update.updated_by, key), fetch=False)
        else:
            query = """
                INSERT INTO system_settings (setting_key, setting_value, updated_by)
                VALUES (%s, %s, %s)
            """
            db_conn.execute_query(query, (key, value_json, update.updated_by), fetch=False)
            
        return {"success": True, "message": f"Setting {key} updated successfully"}
        
    except Exception as e:
        print(f"Error updating setting: {e}")
        raise HTTPException(status_code=500, detail=str(e))
