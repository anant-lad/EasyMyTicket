#!/usr/bin/env python3
"""
Test script for ticket creation API
"""
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:5000')

def test_create_ticket():
    """Test ticket creation"""
    url = f"{API_BASE_URL}/api/tickets/create"
    
    test_ticket = {
        "title": "Email not working in Outlook",
        "description": "I cannot send or receive emails through Outlook. Getting error message 'Connection timeout' when trying to connect to the mail server. This started happening this morning.",
        "user_id": "user123",
        "due_date_time": "2024-12-10 10:00:00"
    }
    
    print("Creating ticket...")
    print(f"Title: {test_ticket['title']}")
    print(f"Description: {test_ticket['description']}\n")
    
    response = requests.post(url, json=test_ticket)
    
    if response.status_code == 201:
        result = response.json()
        print("✅ Ticket created successfully!")
        print(f"Ticket Number: {result['ticket_number']}")
        print("\n📊 Extracted Metadata:")
        print(json.dumps(result['extracted_metadata'], indent=2))
        print("\n🏷️  Classification:")
        print(json.dumps(result['classification'], indent=2))
        print(f"\n📈 Similar tickets found: {result['similar_tickets_found']}")
        return result['ticket_number']
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text)
        return None

def test_get_ticket(ticket_number):
    """Test getting a ticket"""
    url = f"{API_BASE_URL}/api/tickets/{ticket_number}"
    
    print(f"\nRetrieving ticket {ticket_number}...")
    response = requests.get(url)
    
    if response.status_code == 200:
        result = response.json()
        print("✅ Ticket retrieved successfully!")
        print(json.dumps(result['ticket'], indent=2))
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text)

def test_health_check():
    """Test health check endpoint"""
    url = f"{API_BASE_URL}/api/health"
    
    print("Checking API health...")
    response = requests.get(url)
    
    if response.status_code == 200:
        result = response.json()
        print("✅ API is healthy!")
        print(json.dumps(result, indent=2))
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text)

if __name__ == '__main__':
    print("=" * 60)
    print("Ticket Intake Classification System - Test Script")
    print("=" * 60)
    
    # Test health check
    test_health_check()
    print("\n" + "-" * 60 + "\n")
    
    # Test ticket creation
    ticket_number = test_create_ticket()
    
    # Test getting ticket
    if ticket_number:
        print("\n" + "-" * 60 + "\n")
        test_get_ticket(ticket_number)
    
    print("\n" + "=" * 60)


