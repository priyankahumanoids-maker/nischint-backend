"""Test auth role assignment in JWT and /auth/me endpoint."""
import requests
import json
import base64
import os

API_URL = os.environ.get("API_URL", "http://localhost:8001")

def decode_jwt(token: str) -> dict:
    parts = token.split(".")
    payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
    return json.loads(base64.b64decode(payload))

def test_guardian_login_role():
    """Mother account should get role=guardian in JWT and login response."""
    r = requests.post(f"{API_URL}/api/auth/login", json={
        "email": "mothernischint@gmail.com",
        "password": "nischint123"
    })
    assert r.status_code == 200, f"Login failed: {r.text}"
    data = r.json()
    assert data["role"] == "guardian", f"Expected role=guardian, got {data['role']}"
    
    jwt_payload = decode_jwt(data["access_token"])
    assert jwt_payload["role"] == "guardian", f"JWT role should be guardian, got {jwt_payload['role']}"
    assert jwt_payload["email"] == "mothernischint@gmail.com"
    print("PASS: Guardian login role correct")

def test_child_login_role():
    """Child account should get role=child in JWT and login response."""
    r = requests.post(f"{API_URL}/api/auth/login", json={
        "email": "kidnischint@gmail.com",
        "password": "nischint123"
    })
    assert r.status_code == 200, f"Login failed: {r.text}"
    data = r.json()
    assert data["role"] == "child", f"Expected role=child, got {data['role']}"
    
    jwt_payload = decode_jwt(data["access_token"])
    assert jwt_payload["role"] == "child", f"JWT role should be child, got {jwt_payload['role']}"
    assert jwt_payload["email"] == "kidnischint@gmail.com"
    print("PASS: Child login role correct")

def test_guardian_me_endpoint():
    """GET /auth/me should return role=guardian for guardian token."""
    r = requests.post(f"{API_URL}/api/auth/login", json={
        "email": "mothernischint@gmail.com",
        "password": "nischint123"
    })
    token = r.json()["access_token"]
    
    me = requests.get(f"{API_URL}/api/auth/me", headers={
        "Authorization": f"Bearer {token}"
    })
    assert me.status_code == 200, f"/auth/me failed: {me.text}"
    data = me.json()
    assert data["role"] == "guardian", f"/auth/me role should be guardian, got {data['role']}"
    assert data["email"] == "mothernischint@gmail.com"
    print("PASS: Guardian /auth/me role correct")

def test_child_me_endpoint():
    """GET /auth/me should return role=child for child token."""
    r = requests.post(f"{API_URL}/api/auth/login", json={
        "email": "kidnischint@gmail.com",
        "password": "nischint123"
    })
    token = r.json()["access_token"]
    
    me = requests.get(f"{API_URL}/api/auth/me", headers={
        "Authorization": f"Bearer {token}"
    })
    assert me.status_code == 200, f"/auth/me failed: {me.text}"
    data = me.json()
    assert data["role"] == "child", f"/auth/me role should be child, got {data['role']}"
    print("PASS: Child /auth/me role correct")

if __name__ == "__main__":
    test_guardian_login_role()
    test_child_login_role()
    test_guardian_me_endpoint()
    test_child_me_endpoint()
    print("\nAll auth role tests passed!")
