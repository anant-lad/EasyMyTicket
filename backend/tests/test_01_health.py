import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:5000')

def test_health():
    print("\n" + "="*50)
    print("TEST: API Health & Connectivity")
    print("="*50)
    
    response = requests.get(f"{API_BASE_URL}/api/health")
    print(f"Status Code: {response.status_code}")
    
    data = response.json()
    print("Full Response:")
    print(json.dumps(data, indent=2))
    
    assert response.status_code == 200
    assert data['status'] == 'healthy'
    assert data['database'] == 'connected'
    print("\n✅ Health Check Passed")

if __name__ == "__main__":
    test_health()
