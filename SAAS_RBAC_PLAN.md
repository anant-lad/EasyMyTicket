# SaaS RBAC & Provisioning Architecture Plan

## Overview
To function as a true SaaS platform, we must implement a **Hierarchical Provisioning Flow**. Currently, creating an "Organization" only creates the entity record. It does not create a user who can log in to manage it.

## The SaaS Hierarchy
1.  **Super Admin (Platform Owner)**
    *   **Scope**: Entire System.
    *   **Capabilities**: Create Organizations, View All Metrics, Configure Global Settings.
    *   **Key Action**: *Tenant Provisioning* (Create Org + Create Initial Admin).

2.  **Organization Admin (Tenant Admin)**
    *   **Scope**: Single Organization (e.g., "Blackshift", ID: 0002).
    *   **Capabilities**: Manage Users, Manage Technicians, View Org Reports.
    *   **Key Action**: *User Onboarding* (Add Staff).

3.  **Standard User / Technician**
    *   **Scope**: Single Organization.
    *   **Capabilities**: Operational tasks (Create Tickets / Solve Tickets).

## Implementation Plan

### 1. Update Super Admin Workflow (Frontend)
Modify `SuperAdminDashboard.tsx`. When creating a new Organization, we must also capture the details for the **Initial Admin User**.

**New Form Fields in "Add Organization" Modal:**
*   Admin Name
*   Admin Email (will be the User ID or Login Email)
*   Admin Password (Temporary/Initial)

**Logic Change:**
1.  Call `POST /api/organizations/create` -> Returns new `companyid` (e.g., '0002').
2.  **IMMEDIATELY** Call `POST /api/database/users` with:
    *   `user_id`: Admin Email
    *   `user_name`: Admin Name
    *   `role`: `org_admin`
    *   `companyid`: '0002' (from step 1)

### 2. Backend Verification
Ensure `POST /api/database/users` correctly accepts the `role` field.
*Current State*: The `UserCreate` Pydantic model in `database_routes.py` likely needs the `role` field added (it was added to the DB, but maybe not the API model).

### 3. Org Admin Login
Once the above is implemented:
1.  Super Admin creates "Blackshift".
2.  Super Admin enters "admin@blackshift.com" as the admin.
3.  User goes to `/login`.
4.  Selects "Org Admin".
5.  Enters "admin@blackshift.com" + Password.
6.  System logs them in, sees `companyid='0002'`, and routes to `/org/dashboard`.

## Tasks
- [ ] **Backend**: Update `UserCreate` model in `database_routes.py` to include `role`.
- [ ] **Frontend**: Update `SuperAdminDashboard.tsx` to include Admin User fields.
- [ ] **Frontend**: Implement the chained API call (Create Org -> Create Admin).
