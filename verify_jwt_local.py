import json
import urllib.request
import urllib.error
import psycopg2
import os
import sys
# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.config import Config
from src.utils.auth_utils import get_password_hash

# Config
API_URL = "http://localhost:8000/api"
TEST_USER_ID = "test_jwt_user"
TEST_PASSWORD = "password123"
TEST_COMPANY_ID = "9999"

def setup_test_user():
    print(f"Setting up test user: {TEST_USER_ID}...")
    try:
        conn = psycopg2.connect(**Config.get_db_config())
        cursor = conn.cursor()
        
        # 1. Create Organization
        cursor.execute("INSERT INTO organizations (companyid, company_name) VALUES (%s, %s) ON CONFLICT (companyid) DO NOTHING", (TEST_COMPANY_ID, "Test Org"))
        
        # 2. Create User
        hashed = get_password_hash(TEST_PASSWORD)
        cursor.execute("""
            INSERT INTO user_data (user_id, user_name, user_mail, user_password, role, companyid) 
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET 
            user_password = EXCLUDED.user_password,
            companyid = EXCLUDED.companyid,
            role = EXCLUDED.role
        """, (TEST_USER_ID, "Test User", "test@example.com", hashed, "user", TEST_COMPANY_ID))
        
        conn.commit()
        conn.close()
        print("Test user setup complete.")
        return True
    except Exception as e:
        print(f"Setup failed: {e}")
        return False

def test_login():
    print("\nTesting Login...")
    url = f"{API_URL}/auth/login"
    payload = {
        "user_id": TEST_USER_ID,
        "password": TEST_PASSWORD,
        "role": "user"
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                body = response.read().decode('utf-8')
                data = json.loads(body)
                token = data.get("token")
                if token and len(token) > 20: # Crude check for JWT length
                    print("✅ Login Successful. Token received.")
                    return token
                else:
                    print(f"❌ Login Failed. Invalid token format: {token}")
            else:
                print(f"❌ Login Failed. Status: {response.status}")
    except urllib.error.HTTPError as e:
        print(f"❌ Login Failed: HTTP {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"❌ Login Connection Failed: {e}")
    return None

def test_protected_route(token):
    print("\nTesting Protected Route (GET /tickets)...")
    url = f"{API_URL}/tickets?limit=1"
    headers = {"Authorization": f"Bearer {token}"}
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                print("✅ Protected Route Access Successful.")
                print(f"Response: {response.read().decode('utf-8')[:200]}...") # Print first 200 chars
            else:
                print(f"❌ Protected Route Failed. Status: {response.status}")
    except urllib.error.HTTPError as e:
        print(f"❌ Protected Route Failed: HTTP {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"❌ Protected Route Connection Failed: {e}")

    print("\nTesting Unauthorized Access (No Token)...")
    req_no_auth = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req_no_auth) as response:
             print(f"❌ Unauthorized Access NOT Blocked. Status: {response.status}")
    except urllib.error.HTTPError as e:
        if e.code in [401, 403]:
            print(f"✅ Unauthorized Access Blocked Correctly (HTTP {e.code}).")
        else:
            print(f"❌ Unexpected Error: HTTP {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"❌ Connection Failed: {e}")

def cleanup():
    print("\nCleaning up...")
    try:
        conn = psycopg2.connect(**Config.get_db_config())
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_data WHERE user_id = %s", (TEST_USER_ID,))
        cursor.execute("DELETE FROM organizations WHERE companyid = %s", (TEST_COMPANY_ID,))
        conn.commit()
        conn.close()
        print("Cleanup complete.")
    except Exception as e:
        print(f"Cleanup failed: {e}")

if __name__ == "__main__":
    if setup_test_user():
        token = test_login()
        if token:
            test_protected_route(token)
        cleanup()
