import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:5000')

def test_database():
    print("\n" + "="*50)
    print("TEST: Database Exploration API")
    print("="*50)
    
    # Test listing tables
    print("Listing all tables...")
    tables_response = requests.get(f"{API_BASE_URL}/api/database/tables")
    print(f"Tables API Status Code: {tables_response.status_code}")
    data = tables_response.json()
    print("Tables List Response:")
    print(json.dumps(data, indent=2))
    
    tables = data.get('tables', [])
    table_names = [t['table_name'] for t in tables]
    assert 'new_tickets' in table_names
    assert 'technician_data' in table_names
    
    # Test getting table data
    print("\nRetrieving sample data from 'new_tickets'...")
    data_response = requests.get(f"{API_BASE_URL}/api/database/tables/new_tickets/data?limit=2")
    print(f"Data API Status Code: {data_response.status_code}")
    res_data = data_response.json()
    print("Table Data Response:")
    print(json.dumps(res_data, indent=2))
    
    assert res_data['success'] == True
    assert 'data' in res_data
    
    print(f"\n✅ Database API Test Passed (Found {len(tables)} tables)")

if __name__ == "__main__":
    test_database()
