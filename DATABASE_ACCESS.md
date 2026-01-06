# Database Public Access Guide

This document provides instructions for connecting to the PostgreSQL database remotely.

## Connection Details

To connect to the database, you will need the following information from the database administrator:

- **Host**: Your public IP address or domain name
- **Port**: `5433`
- **Database**: `tickets_db`
- **Username**: `admin`
- **Password**: (Provided by administrator)

## Connection String Format

### PostgreSQL Connection String (URI format)
```
postgresql://admin:YOUR_PASSWORD@YOUR_PUBLIC_IP:5433/tickets_db
```

### Connection Parameters (Key-Value format)
```
host=YOUR_PUBLIC_IP
port=5433
database=tickets_db
user=admin
password=YOUR_PASSWORD
```

## Connecting from Different Tools

### 1. Using psql (Command Line)

```bash
psql -h YOUR_PUBLIC_IP -p 5433 -U admin -d tickets_db
```

You will be prompted for the password.

### 2. Using Python (psycopg2)

```python
import psycopg2

conn = psycopg2.connect(
    host="YOUR_PUBLIC_IP",
    port=5433,
    database="tickets_db",
    user="admin",
    password="YOUR_PASSWORD"
)
```

### 3. Using pgAdmin

1. Open pgAdmin
2. Right-click on "Servers" → "Create" → "Server"
3. In the "General" tab, enter a name for the server
4. In the "Connection" tab:
   - **Host name/address**: `YOUR_PUBLIC_IP`
   - **Port**: `5433`
   - **Maintenance database**: `tickets_db`
   - **Username**: `admin`
   - **Password**: `YOUR_PASSWORD`
5. Click "Save"

### 4. Using DBeaver

1. Open DBeaver
2. Click "New Database Connection"
3. Select "PostgreSQL"
4. Enter connection details:
   - **Host**: `YOUR_PUBLIC_IP`
   - **Port**: `5433`
   - **Database**: `tickets_db`
   - **Username**: `admin`
   - **Password**: `YOUR_PASSWORD`
5. Click "Test Connection" to verify
6. Click "Finish"

### 5. Using SQLAlchemy (Python)

```python
from sqlalchemy import create_engine

connection_string = f"postgresql://admin:YOUR_PASSWORD@YOUR_PUBLIC_IP:5433/tickets_db"
engine = create_engine(connection_string)
```

## Finding Your Public IP Address

The database administrator needs to provide you with the public IP address. You can also find it using:

```bash
# Linux/Mac
curl ifconfig.me

# Or
curl ipinfo.io/ip

# Windows (PowerShell)
Invoke-RestMethod -Uri https://api.ipify.org
```

## Security Best Practices

1. **Use Strong Passwords**: Always use a strong, unique password for database access
2. **Limit Access**: Only share credentials with authorized users
3. **Use VPN (Recommended)**: For production environments, consider using a VPN instead of direct public access
4. **Firewall Rules**: The administrator should configure firewall rules to restrict access to known IP addresses when possible
5. **SSL/TLS**: For production use, enable SSL/TLS encryption (contact administrator)
6. **Regular Updates**: Keep your database client tools updated

## Troubleshooting

### Connection Refused

**Error**: `Connection refused` or `could not connect to server`

**Possible Causes**:
- The database server is not running
- The port (5433) is blocked by a firewall
- The public IP address is incorrect
- Port forwarding is not configured on the router

**Solutions**:
- Verify the database server is running
- Check with the administrator that port forwarding is configured
- Verify the public IP address is correct
- Check if your firewall allows outbound connections on port 5433

### Authentication Failed

**Error**: `password authentication failed for user "admin"`

**Possible Causes**:
- Incorrect password
- Username is incorrect
- User does not have permission to connect from your IP

**Solutions**:
- Double-check the password (case-sensitive)
- Verify the username is `admin`
- Contact the administrator to verify your IP is allowed

### Timeout Errors

**Error**: `Connection timeout` or `Operation timed out`

**Possible Causes**:
- Network connectivity issues
- Firewall blocking the connection
- The server is behind a NAT/router that doesn't forward the port

**Solutions**:
- Check your internet connection
- Try pinging the public IP address
- Contact the administrator to verify network configuration

### Host Not Resolved

**Error**: `could not translate host name` or `Name or service not known`

**Possible Causes**:
- Invalid hostname or IP address
- DNS resolution issues

**Solutions**:
- Use the IP address instead of a hostname
- Verify the IP address is correct
- Check your DNS settings

## Network Configuration (For Administrators)

To enable public access, the following must be configured:

1. **PostgreSQL Configuration**: The database is configured to listen on all interfaces (`listen_addresses = '*'`)
2. **Host-Based Authentication**: `pg_hba.conf` allows remote connections with password authentication
3. **Port Forwarding**: Router must forward external port 5433 to the server's local IP on port 5433
4. **Firewall**: Server firewall must allow incoming connections on port 5433

### Setting Up Port Forwarding

1. Access your router's admin panel (usually `192.168.1.1` or `192.168.0.1`)
2. Navigate to "Port Forwarding" or "Virtual Server" settings
3. Add a new rule:
   - **External Port**: `5433`
   - **Internal IP**: Your server's local IP (e.g., `192.168.1.100`)
   - **Internal Port**: `5433`
   - **Protocol**: TCP
4. Save and apply the changes

### Firewall Configuration

**Linux (ufw)**:
```bash
sudo ufw allow 5433/tcp
```

**Linux (iptables)**:
```bash
sudo iptables -A INPUT -p tcp --dport 5433 -j ACCEPT
```

**Windows Firewall**:
1. Open Windows Defender Firewall
2. Click "Advanced settings"
3. Create a new Inbound Rule for port 5433 (TCP)

## Support

If you encounter issues connecting to the database, please contact the database administrator with:
- The exact error message
- Your public IP address
- The tool/client you're using to connect
- Any relevant network information

## Database Schema

### `new_tickets`
Main table for newly created tickets.
- `assigned_tech_id` (VARCHAR): ID of the technician currently assigned.
- `status` (VARCHAR): Current lifecycle status (New, Assigned, In Progress, Resolved).

### `technician_data`
Stores technician profiles.
- `tech_id` (PRIMARY KEY)
- `tech_role`: e.g., Senior, Junior, Support.
- `technical_skills`: Comma-separated or list of matched skills.
- `status`: availability (available, on_leave, away, etc.)
- `current_workload`: Number of active tickets.
- `solved_tickets`: Total resolved tickets.

### `ticket_assignments`
History of assignment events.
- `ticket_number`
- `tech_id`
- `assigned_at`
- `unassigned_at`
- `assignment_status`: assigned, resolved, re-assigned.

### `user_data`
End-user profiles.
- `user_id`, `user_name`, `user_mail`.

