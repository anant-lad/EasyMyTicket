import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:5000')

def test_assignment():
    print("\n" + "="*50)
    print("TEST: Smart Ticket Assignment")
    print("="*50)
    
    payload = {
        "title": "VPN connection issues on MacBook",
        "description": "I am unable to connect to the corporate VPN from my laptop.",
        "user_id": "test_user"
    }
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(f"{API_BASE_URL}/api/tickets/create", json=payload)
    print(f"Status Code: {response.status_code}")
    
    assert response.status_code == 201
    data = response.json()
    print("Full Response Data:")
    print(json.dumps(data, indent=2))
    
    assigned_tech_id = data.get('assigned_tech_id')
    assert assigned_tech_id is not None
    
    ticket_num = data.get('ticket_number')
    print(f"\nVerifying assignment history for {ticket_num}...")
    history_response = requests.get(f"{API_BASE_URL}/api/database/tickets/{ticket_num}/assignments")
    print(f"History API Status Code: {history_response.status_code}")
    
    history = history_response.json()
    print("Assignment History:")
    print(json.dumps(history, indent=2))
    
    assert len(history) > 0
    assert history[0]['tech_id'] == assigned_tech_id
    
    print(f"\n✅ Assignment Test Passed (Assigned to: {assigned_tech_id})")

if __name__ == "__main__":
    test_assignment()
