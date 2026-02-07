
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
from src.database.db_connection import DatabaseConnection
from src.utils.auth_utils import verify_password, get_password_hash

router = APIRouter()

_db_conn = None

def get_db_connection():
    global _db_conn
    if _db_conn is None:
        _db_conn = DatabaseConnection()
    return _db_conn

class LoginRequest(BaseModel):
    user_id: str
    password: str
    role: str  # 'user', 'technician', 'org_admin', 'super_admin'

class LoginResponse(BaseModel):
    success: bool
    message: str
    user: Optional[Dict[str, Any]] = None
    token: Optional[str] = None

@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    try:
        db = get_db_connection()
        user_data = None
        
        # Determine which table to query
        if request.role in ['user', 'org_admin', 'super_admin']:
            # Query user_data by user_id OR user_mail
            query = "SELECT * FROM user_data WHERE user_id = %s OR user_mail = %s"
            # Pass the input twice for the OR condition
            users = db.execute_query(query, (request.user_id, request.user_id))
            
            if users:
                user = users[0]
                # Check if role matches (except for super_admin who might login as user?)
                # For now, enforce role check if it's stored
                stored_role = user.get('role', 'user')
                if request.role != stored_role:
                     # Allow super_admin to login if they selected super_admin but stored as something else? No.
                     # But allow 'user' login if stored is 'org_admin'? Maybe not for security.
                     if stored_role == 'super_admin' and request.role == 'super_admin':
                         pass
                     elif stored_role == 'org_admin' and request.role == 'org_admin':
                         pass
                     elif stored_role == 'user' and request.role == 'user':
                         pass
                     else:
                         return LoginResponse(success=False, message=f"Role mismatch. Registered as {stored_role}")

                # Verify Password (check password_hash first, then fallback to user_password)
                hashed = user.get('password_hash')
                plain = user.get('user_password')
                
                is_valid = False
                if hashed:
                    is_valid = verify_password(request.password, hashed)
                elif plain:
                    # Fallback to plain text check
                    is_valid = (plain == request.password)
                    # Optional: specific logic to upgrade to hash here? 
                
                if is_valid:
                    # Remove password fields before returning
                    user.pop('user_password', None)
                    user.pop('password_hash', None)
                    user_data = user
                    
        elif request.role == 'technician':
            # Query technician_data by tech_id OR tech_mail
            query = "SELECT * FROM technician_data WHERE tech_id = %s OR tech_mail = %s"
            techs = db.execute_query(query, (request.user_id, request.user_id))
            
            if techs:
                tech = techs[0]
                hashed = tech.get('password_hash') # Needs to be added to tech table too if not present
                plain = tech.get('tech_password')
                
                is_valid = False
                if hashed: 
                    is_valid = verify_password(request.password, hashed)
                elif plain:
                    is_valid = (plain == request.password)
                
                if is_valid:
                    tech.pop('tech_password', None)
                    tech.pop('password_hash', None)
                    # Normalize fields for frontend
                    tech['user_id'] = tech['tech_id']
                    tech['user_name'] = tech['tech_name']
                    tech['user_mail'] = tech['tech_mail']
                    tech['role'] = 'technician'
                    user_data = tech

        if user_data:
            return LoginResponse(
                success=True, 
                message="Login successful", 
                user=user_data,
                token=f"dummy-token-{request.user_id}" # Implement JWT later
            )
        else:
            return LoginResponse(success=False, message="Invalid credentials")

    except Exception as e:
        print(f"Login error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
