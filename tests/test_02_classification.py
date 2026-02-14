import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:5000')

def test_classification():
    print("\n" + "="*50)
    print("TEST: Ticket Intake & Classification")
    print("="*50)
    
    payload = {
        "title": "Hardware: Printer jammed in Room 302",
        "description": "The big laser printer in the marketing office has a paper jam and won't start.",
        "user_id": "test_user"
    }
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(f"{API_BASE_URL}/api/tickets/create", json=payload)
    print(f"Status Code: {response.status_code}")
    
    assert response.status_code == 201
    data = response.json()
    print("Full Response Data:")
    print(json.dumps(data, indent=2))
    
    classification = data.get('classification', {})
    issue_type = classification.get('ISSUETYPE', {})
    issue_label = issue_type.get('Label', '')
    
    assert 'Hardware' in issue_label or 'Printer' in issue_label
    print(f"\n✅ Classification Test Passed (Issue Type: {issue_label})")

if __name__ == "__main__":
    test_classification()
