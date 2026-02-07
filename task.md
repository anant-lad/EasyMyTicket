# Multi-Tenant RBAC Implementation Tasks

- [x] **Database Schema Migration**
    - [x] Add `companyid`, `role`, `password_hash` to `user_data` table.
    - [x] Add `companyid`, `role` to `technician_data` table.
    - [x] Verify schema changes.

- [x] **Frontend Implementation**
    - [x] **Type Definitions**: Update `src/types/index.ts` with new roles (`super_admin`, `org_admin`).
    - [x] **Authentication**: Update `AuthContext.tsx` to handle new roles and routing.
    - [x] **Login Page**: Update `Login.tsx` UI to allow selecting Admin roles (or auto-detect).
    - [x] **Super Admin Dashboard**: Create `src/pages/admin/SuperAdminDashboard.tsx` for managing Organizations.
    - [x] **Org Admin Dashboard**: Create `src/pages/org/OrgAdminDashboard.tsx` for managing Users/Technicians.
    - [x] **Routing**: Update `App.tsx` with protected routes for new dashboards.

- [x] **SaaS Provisioning**
    - [x] Update `SuperAdminDashboard` to capture Initial Admin details.
    - [x] Implement chained API call (Create Org -> Create Admin).
    - [x] Verify Backend models support `role`.

- [x] **Security Hardening**
    - [x] Install `passlib` and `bcrypt`.
    - [x] Create Secure Login Endpoint (`POST /api/auth/login`).
    - [x] Implement Password Hashing in Database Routes.
    - [x] Remove Client-Side Password Checks (Update `AuthContext`).

- [ ] **Backend Verification**
    - [ ] Verify `super_admin` can create organizations.
    - [ ] Verify `org_admin` can create users/technicians (linked to their `companyid`).
