#!/usr/bin/env python3
"""
Basic API test script
Tests core endpoints to verify deployment
"""

import requests
import sys
import json

def test_health(base_url):
    """Test health endpoint"""
    print("Testing health endpoint...")
    response = requests.get(f"{base_url}/api/health")
    if response.status_code == 200:
        print("✓ Health check passed")
        return True
    else:
        print(f"✗ Health check failed: {response.status_code}")
        return False

def test_register(base_url):
    """Test patient registration"""
    print("\nTesting patient registration...")
    data = {
        "firstName": "Test",
        "lastName": "Patient",
        "age": 75,
        "gender": "Male"
    }
    response = requests.post(f"{base_url}/api/patient/register", json=data)
    if response.status_code == 201:
        result = response.json()
        print(f"✓ Registration successful")
        print(f"  Patient Code: {result['patientCode']}")
        print(f"  Code Hash: {result['codeHash']}")
        return result
    else:
        print(f"✗ Registration failed: {response.status_code}")
        print(response.text)
        return None

def test_dementia_stats(base_url):
    """Test RAG statistics"""
    print("\nTesting dementia RAG stats...")
    response = requests.get(f"{base_url}/api/dementia/stats")
    if response.status_code == 200:
        stats = response.json()
        print(f"✓ RAG stats retrieved")
        print(f"  Research Papers: {stats.get('research_papers', 0)}")
        print(f"  Indexed Chunks: {stats.get('indexed_chunks', 0)}")
        return True
    else:
        print(f"✗ RAG stats failed: {response.status_code}")
        return False

def test_dementia_query(base_url, code_hash):
    """Test dementia query"""
    print("\nTesting dementia query...")
    data = {
        "codeHash": code_hash,
        "query": "What are effective strategies for managing medication adherence in dementia patients?"
    }
    response = requests.post(f"{base_url}/api/dementia/query", json=data)
    if response.status_code == 200:
        result = response.json()
        print("✓ Query successful")
        print(f"  Answer length: {len(result.get('answer', ''))} characters")
        print(f"  Sources: {len(result.get('sources', []))} research papers cited")
        return True
    else:
        print(f"✗ Query failed: {response.status_code}")
        print(response.text)
        return False

def main():
    """Run API tests"""
    if len(sys.argv) < 2:
        print("Usage: python test_api.py <service_url>")
        print("Example: python test_api.py https://your-service.run.app")
        sys.exit(1)
    
    base_url = sys.argv[1].rstrip('/')
    
    print("="*60)
    print("loveUAD API Test Suite")
    print("="*60)
    print(f"Testing: {base_url}\n")
    
    # Test health
    if not test_health(base_url):
        print("\n✗ Health check failed. Stopping tests.")
        sys.exit(1)
    
    # Test registration
    registration = test_register(base_url)
    if not registration:
        print("\n✗ Registration failed. Stopping tests.")
        sys.exit(1)
    
    # Test RAG stats
    test_dementia_stats(base_url)
    
    # Test dementia query (only if papers are loaded)
    code_hash = registration.get('codeHash')
    test_dementia_query(base_url, code_hash)
    
    print("\n" + "="*60)
    print("Tests complete!")
    print("="*60)

if __name__ == '__main__':
    main()
