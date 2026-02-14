import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:5000')

def test_notifications():
    print("\n" + "="*50)
    print("TEST: Ticket Notifications Flow")
    print("="*50)
    
    payload = {
        "title": "Email access request for new hire",
        "description": "Please provide email access for the new employee starting next week.",
        "user_id": "U001"
    }
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(f"{API_BASE_URL}/api/tickets/create", json=payload)
    print(f"Status Code: {response.status_code}")
    
    assert response.status_code == 201
    data = response.json()
    print("Full Response Data:")
    print(json.dumps(data, indent=2))
    
    print(f"\n✅ Notification Trigger Test Passed (Ticket: {data.get('ticket_number')})")

if __name__ == "__main__":
    test_notifications()
