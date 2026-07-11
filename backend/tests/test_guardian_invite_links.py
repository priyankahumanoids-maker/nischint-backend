"""
Guardian Invite Links Feature Tests
- POST /api/guardian-network/invite - Create invite
- GET /api/guardian-network/invite/{token} - Get invite (public)
- GET /api/guardian-network/invites - List user's invites
- POST /api/guardian-network/invite/{token}/accept - Accept invite
- DELETE /api/guardian-network/invite/{token} - Revoke invite
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')

class TestGuardianInviteLinks:
    """Guardian Invite Links Feature Tests"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json().get("access_token")
    
    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Get authorization headers"""
        return {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json"
        }
    
    @pytest.fixture(scope="class")
    def test_invite_token(self, auth_headers):
        """Create a test invite and return the token"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/invite",
            headers=auth_headers,
            json={
                "guardian_name": "TEST_Invite_User",
                "guardian_email": "test_invite@example.com",
                "relationship_type": "friend"
            }
        )
        assert response.status_code == 201, f"Failed to create test invite: {response.text}"
        data = response.json()
        return data["invite"]["invite_token"]

    # Test 1: POST /api/guardian-network/invite - Create invite
    def test_create_invite(self, auth_headers):
        """Test creating a guardian invite"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/invite",
            headers=auth_headers,
            json={
                "guardian_name": "TEST_Create_Invite",
                "guardian_email": "test_create@example.com",
                "relationship_type": "parent"
            }
        )
        assert response.status_code == 201, f"Create invite failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "invite" in data, "Response should contain 'invite'"
        assert "invite_url" in data, "Response should contain 'invite_url'"
        assert "share_message" in data, "Response should contain 'share_message'"
        
        invite = data["invite"]
        assert "invite_token" in invite, "Invite should have token"
        assert invite["status"] == "pending", "New invite should be pending"
        assert invite["relationship_type"] == "parent"
        assert invite["guardian_name"] == "TEST_Create_Invite"
        assert invite["guardian_email"] == "test_create@example.com"
        assert "inviter_name" in invite, "Invite should have inviter_name"
        assert "expires_at" in invite, "Invite should have expires_at"
        
        # Verify invite_url format
        assert invite["invite_token"] in data["invite_url"], "invite_url should contain token"

    # Test 2: GET /api/guardian-network/invite/{token} - Get invite (public, no auth)
    def test_get_invite_public(self, test_invite_token):
        """Test getting invite details without auth (public endpoint)"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/invite/{test_invite_token}",
            headers={"Content-Type": "application/json"}  # No auth header
        )
        assert response.status_code == 200, f"Get invite failed: {response.text}"
        data = response.json()
        
        assert "invite" in data
        assert "already_accepted" in data
        assert data["already_accepted"] == False
        
        invite = data["invite"]
        assert invite["invite_token"] == test_invite_token
        assert invite["status"] == "pending"
        assert "inviter_name" in invite
        assert "relationship_type" in invite

    # Test 3: GET /api/guardian-network/invites - List user's invites
    def test_list_invites(self, auth_headers):
        """Test listing user's invites"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/invites",
            headers=auth_headers
        )
        assert response.status_code == 200, f"List invites failed: {response.text}"
        data = response.json()
        
        assert "invites" in data
        assert "total" in data
        assert isinstance(data["invites"], list)
        assert data["total"] >= 1, "Should have at least 1 invite"

    # Test 4: GET /api/guardian-network/invite/{invalid_token} - 404 for invalid token
    def test_get_invite_invalid_token(self):
        """Test getting invite with invalid token returns 404"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/invite/invalid_token_12345",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 404, f"Expected 404 for invalid token, got {response.status_code}"

    # Test 5: DELETE /api/guardian-network/invite/{token} - Revoke invite
    def test_revoke_invite(self, auth_headers):
        """Test revoking a pending invite"""
        # First create a new invite to revoke
        create_response = requests.post(
            f"{BASE_URL}/api/guardian-network/invite",
            headers=auth_headers,
            json={
                "guardian_name": "TEST_Revoke_Invite",
                "relationship_type": "sibling"
            }
        )
        assert create_response.status_code == 201
        token = create_response.json()["invite"]["invite_token"]
        
        # Revoke the invite
        revoke_response = requests.delete(
            f"{BASE_URL}/api/guardian-network/invite/{token}",
            headers=auth_headers
        )
        assert revoke_response.status_code == 200, f"Revoke failed: {revoke_response.text}"
        assert revoke_response.json()["status"] == "revoked"
        
        # Verify the invite is now revoked (should return 410)
        get_response = requests.get(
            f"{BASE_URL}/api/guardian-network/invite/{token}"
        )
        assert get_response.status_code == 410, "Revoked invite should return 410"

    # Test 6: Create invite without auth should fail
    def test_create_invite_without_auth(self):
        """Test that creating invite without auth returns 401"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/invite",
            headers={"Content-Type": "application/json"},
            json={
                "guardian_name": "Unauthorized",
                "relationship_type": "friend"
            }
        )
        assert response.status_code in [401, 403], f"Expected 401/403 without auth, got {response.status_code}"

    # Test 7: Accept invite requires auth
    def test_accept_invite_requires_auth(self, test_invite_token):
        """Test that accepting invite requires authentication"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/invite/{test_invite_token}/accept",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code in [401, 403], f"Expected 401/403 without auth, got {response.status_code}"

    # Test 8: Different relationship types
    @pytest.mark.parametrize("rel_type", ["parent", "friend", "sibling", "spouse", "campus_security", "other"])
    def test_create_invite_relationship_types(self, auth_headers, rel_type):
        """Test creating invites with different relationship types"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/invite",
            headers=auth_headers,
            json={
                "guardian_name": f"TEST_{rel_type}_Invite",
                "relationship_type": rel_type
            }
        )
        assert response.status_code == 201, f"Failed for {rel_type}: {response.text}"
        assert response.json()["invite"]["relationship_type"] == rel_type

    # Test 9: Verify existing invite token works
    def test_existing_invite_token(self):
        """Test the provided existing invite token"""
        token = "LKVozd2a-impnE-2cZTnrzxEaVMJ8m6K5wAQk4EZclw"
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/invite/{token}"
        )
        # Token may be expired or valid - both are acceptable
        assert response.status_code in [200, 410], f"Unexpected status: {response.status_code}"

    # Test 10: Self-invite prevention test
    def test_self_invite_prevention(self, auth_headers, test_invite_token):
        """Test that user cannot accept their own invite"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/invite/{test_invite_token}/accept",
            headers=auth_headers
        )
        # Should return 400 because user cannot accept their own invite
        assert response.status_code == 400, f"Expected 400 for self-invite, got {response.status_code}"
        assert "own invite" in response.json().get("detail", "").lower()
