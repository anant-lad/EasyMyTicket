import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:5000')

def test_resolution():
    print("\n" + "="*50)
    print("TEST: AI Resolution Generation")
    print("="*50)
    
    payload = {
        "title": "Teams not showing profile picture",
        "description": "I changed my profile picture in Office 365 but it is not reflecting in Microsoft Teams.",
        "user_id": "test_user"
    }
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(f"{API_BASE_URL}/api/tickets/create", json=payload)
    print(f"Status Code: {response.status_code}")
    
    assert response.status_code == 201
    data = response.json()
    print("Full Response Data (partial):")
    # Only print first 500 chars of resolution to avoid log bloat
    resolution = data.get('resolution', '')
    data_display = {k: v for k, v in data.items() if k != 'resolution'}
    print(json.dumps(data_display, indent=2))
    print(f"Resolution Snippet: {resolution[:500]}...")
    
    assert resolution is not None
    assert "Step 1" in resolution
    
    ticket_num = data.get('ticket_number')
    print(f"\nVerifying resolution retrieval API for {ticket_num}...")
    res_response = requests.get(f"{API_BASE_URL}/api/tickets/{ticket_num}/resolution")
    print(f"Resolution API Status Code: {res_response.status_code}")
    
    assert res_response.json()['resolution'] == resolution
    print(f"\n✅ Resolution Test Passed (Length: {len(resolution)})")

if __name__ == "__main__":
    test_resolution()
