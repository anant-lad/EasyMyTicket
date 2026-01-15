"""
Organization management routes
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


# Pydantic models for request/response
class OrganizationCreateRequest(BaseModel):
    """Request model for organization creation"""
    company_name: str = Field(..., description="Company/Organization name", min_length=1)
    company_email: Optional[str] = Field(None, description="Company email address")
    contact_phone: Optional[str] = Field(None, description="Contact phone number")
    address: Optional[str] = Field(None, description="Company address")
    
    class Config:
        json_schema_extra = {
            "example": {
                "company_name": "Acme Corporation",
                "company_email": "contact@acme.com",
                "contact_phone": "+1-555-1234",
                "address": "123 Main St, City, State 12345"
            }
        }


class OrganizationResponse(BaseModel):
    """Response model for organization creation"""
    success: bool
    companyid: str
    organization: Dict[str, Any]


class OrganizationDetailResponse(BaseModel):
    """Response model for organization details"""
    success: bool
    organization: Dict[str, Any]


class OrganizationsListResponse(BaseModel):
    """Response model for organizations list"""
    success: bool
    organizations: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int
    has_more: bool


@router.post("/organizations/create", response_model=OrganizationResponse, status_code=201)
async def create_organization(org_request: OrganizationCreateRequest):
    """
    Create a new organization with auto-generated companyid
    
    This endpoint:
    1. Auto-generates companyid starting from "0001"
    2. Stores organization details
    3. Returns the created organization with companyid
    
    Returns:
        OrganizationResponse with organization details and companyid
    """
    try:
        db_conn = get_db_connection()
        
        # Prepare organization data
        organization_data = {
            'company_name': org_request.company_name,
            'company_email': org_request.company_email,
            'contact_phone': org_request.contact_phone,
            'address': org_request.address
        }
        
        print("\n" + "="*80)
        print("🏢 ORGANIZATION CREATION REQUEST RECEIVED")
        print("="*80)
        print(f"📝 Company Name: {organization_data['company_name']}")
        print(f"📧 Email: {organization_data.get('company_email', 'N/A')}")
        print(f"📞 Phone: {organization_data.get('contact_phone', 'N/A')}")
        print("="*80)
        
        # Create organization
        companyid = db_conn.create_organization(organization_data)
        
        if not companyid:
            raise HTTPException(
                status_code=500,
                detail='Failed to create organization'
            )
        
        # Fetch created organization
        created_org = db_conn.get_organization_by_companyid(companyid)
        
        # Convert datetime objects to strings
        if created_org:
            for key, value in created_org.items():
                if isinstance(value, datetime):
                    created_org[key] = value.isoformat()
        
        print(f"✅ Organization created successfully!")
        print(f"🏢 Company ID: {companyid}")
        print("="*80 + "\n")
        
        return OrganizationResponse(
            success=True,
            companyid=companyid,
            organization=created_org
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating organization: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f'Internal server error: {str(e)}'
        )


@router.get("/organizations", response_model=OrganizationsListResponse)
async def get_all_organizations(
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of organizations to return"),
    offset: int = Query(0, ge=0, description="Number of organizations to skip")
):
    """
    Get all organizations with pagination
    
    Query Parameters:
        - limit: Maximum number of organizations to return (1-1000, default: 100)
        - offset: Number of organizations to skip for pagination (default: 0)
    
    Returns:
        OrganizationsListResponse with list of organizations and pagination info
    """
    try:
        db_conn = get_db_connection()
        
        result = db_conn.get_all_organizations(limit=limit, offset=offset)
        
        # Convert datetime objects to strings for JSON serialization
        organizations = []
        for org in result['organizations']:
            org_dict = dict(org)
            for key, value in org_dict.items():
                if isinstance(value, datetime):
                    org_dict[key] = value.isoformat()
            organizations.append(org_dict)
        
        return OrganizationsListResponse(
            success=True,
            organizations=organizations,
            total=result['total'],
            limit=result['limit'],
            offset=result['offset'],
            has_more=result['has_more']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving organizations: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f'Internal server error: {str(e)}'
        )


@router.get("/organizations/{companyid}", response_model=OrganizationDetailResponse)
async def get_organization(companyid: str):
    """
    Get organization details by companyid
    
    Args:
        companyid: The company ID to retrieve
    
    Returns:
        OrganizationDetailResponse with organization details
    """
    try:
        db_conn = get_db_connection()
        
        organization = db_conn.get_organization_by_companyid(companyid)
        
        if not organization:
            raise HTTPException(
                status_code=404,
                detail=f'Organization with companyid {companyid} not found'
            )
        
        # Convert datetime objects to strings
        org_dict = dict(organization)
        for key, value in org_dict.items():
            if isinstance(value, datetime):
                org_dict[key] = value.isoformat()
        
        return OrganizationDetailResponse(
            success=True,
            organization=org_dict
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving organization: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f'Internal server error: {str(e)}'
        )
