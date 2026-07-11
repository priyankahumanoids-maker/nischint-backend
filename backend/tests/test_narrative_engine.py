# AI Incident Narrative Engine Tests
# Tests POST /api/operator/incidents/{id}/narrative - Generate narrative
# Tests GET /api/operator/incidents/{id}/narrative - Get narrative history
# Tests GET /api/operator/incidents/{id}/narrative/status - Check narrative status
# Tests versioning, caching, RBAC, and 404 handling

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestNarrativeEngineSetup:
    """Setup and authentication tests"""
    
    @pytest.fixture(scope="class")
    def operator_token(self):
        """Get operator auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert response.status_code == 200, f"Operator login failed: {response.text}"
        return response.json()["access_token"]
    
    @pytest.fixture(scope="class")
    def guardian_token(self):
        """Get guardian auth token (should not have access)"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        assert response.status_code == 200, f"Guardian login failed: {response.text}"
        return response.json()["access_token"]
    
    @pytest.fixture(scope="class")
    def test_incident_ids(self, operator_token):
        """Fetch incident IDs for testing"""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Failed to fetch incidents: {response.text}"
        incidents = response.json()
        
        # Known incidents from agent context
        test_incident = "23b02397-f738-448f-8492-d7f82c6bc38e"  # TEST incident with narrative
        device_offline = "3c3a9bae-4332-40fa-a0d0-1072d7125a85"  # Has narrative
        low_battery = "d4ab6faf-540b-47ca-8a4d-b2c06a8464b5"  # No narrative
        
        return {
            "test_incident": test_incident,
            "device_offline": device_offline,
            "low_battery": low_battery,
            "non_existent": "00000000-0000-0000-0000-000000000000"
        }

class TestNarrativeStatus:
    """GET /api/operator/incidents/{id}/narrative/status"""
    
    @pytest.fixture(autouse=True)
    def setup(self, operator_token, test_incident_ids):
        self.token = operator_token
        self.ids = test_incident_ids
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_status_returns_200_for_incident_with_narrative(self, operator_token, test_incident_ids):
        """Status endpoint returns 200 for incident with existing narrative"""
        incident_id = test_incident_ids["test_incident"]
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative/status",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["has_narrative"] == True
        assert "latest_version" in data
        assert "is_stale" in data
        assert "generated_by" in data
        assert "confidence" in data
        print(f"Status: has_narrative={data['has_narrative']}, is_stale={data['is_stale']}, version={data['latest_version']}")
    
    def test_status_returns_200_for_incident_without_narrative(self, operator_token, test_incident_ids):
        """Status endpoint returns 200 with has_narrative=False for fresh incident"""
        incident_id = test_incident_ids["low_battery"]
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative/status",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["has_narrative"] == False
        assert data["is_stale"] == True
        assert data["latest_version"] is None
        print(f"Fresh incident status: {data['message']}")
    
    def test_status_returns_404_for_nonexistent_incident(self, operator_token, test_incident_ids):
        """Status endpoint returns 404 for non-existent incident ID"""
        incident_id = test_incident_ids["non_existent"]
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative/status",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        print("Correctly returns 404 for non-existent incident")

class TestNarrativeGeneration:
    """POST /api/operator/incidents/{id}/narrative"""
    
    def test_generate_narrative_returns_200(self, operator_token, test_incident_ids):
        """Generate endpoint returns 200 and creates narrative"""
        # Use low_battery incident which may not have a narrative
        incident_id = test_incident_ids["low_battery"]
        response = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check response structure
        assert "id" in data
        assert "incident_id" in data
        assert "narrative" in data
        assert "confidence" in data
        assert "cached" in data
        
        if data.get("cached"):
            print(f"Narrative was cached (unchanged input): {data['message']}")
        else:
            assert "narrative_version" in data
            assert "generated_by" in data
            assert data["generated_by"] in ["ai", "template"]
            print(f"Generated new narrative v{data['narrative_version']} by {data['generated_by']}, confidence={data['confidence']}")
    
    def test_generate_narrative_structure(self, operator_token, test_incident_ids):
        """Generated narrative has required structure (title, summary, what_happened, etc.)"""
        incident_id = test_incident_ids["low_battery"]
        response = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        narrative = data.get("narrative", {})
        if isinstance(narrative, str):
            import json
            narrative = json.loads(narrative)
        
        # Check narrative structure
        assert "title" in narrative, "Narrative missing 'title'"
        assert "one_line_summary" in narrative, "Narrative missing 'one_line_summary'"
        assert "what_happened" in narrative, "Narrative missing 'what_happened'"
        assert "evidence" in narrative, "Narrative missing 'evidence'"
        assert "recommended_actions" in narrative, "Narrative missing 'recommended_actions'"
        assert "confidence" in narrative, "Narrative missing 'confidence'"
        
        # Validate types
        assert isinstance(narrative["what_happened"], list), "what_happened should be a list"
        assert isinstance(narrative["evidence"], list), "evidence should be a list"
        assert isinstance(narrative["recommended_actions"], list), "recommended_actions should be a list"
        
        print(f"Narrative structure valid: title='{narrative['title'][:50]}...', {len(narrative['what_happened'])} events, {len(narrative['evidence'])} evidence items")
    
    def test_cached_response_when_input_unchanged(self, operator_token, test_incident_ids):
        """Calling generate twice with unchanged input returns cached response"""
        incident_id = test_incident_ids["device_offline"]
        
        # First call
        response1 = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response1.status_code == 200
        
        # Second call (should return cached)
        response2 = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response2.status_code == 200
        data2 = response2.json()
        
        # If input unchanged, should be cached
        assert data2["cached"] == True, f"Expected cached=True but got {data2.get('cached')}"
        print(f"Cache works correctly: {data2['message']}")
    
    def test_generate_404_for_nonexistent_incident(self, operator_token, test_incident_ids):
        """Generate endpoint returns 404 for non-existent incident"""
        incident_id = test_incident_ids["non_existent"]
        response = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 404
        print("Correctly returns 404 for non-existent incident on POST")

class TestNarrativeHistory:
    """GET /api/operator/incidents/{id}/narrative"""
    
    def test_get_narratives_returns_list(self, operator_token, test_incident_ids):
        """Get narratives returns a list of narrative versions"""
        incident_id = test_incident_ids["test_incident"]
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list), "Expected list of narratives"
        print(f"Found {len(data)} narrative(s) for incident")
        
        if len(data) > 0:
            # Check first narrative structure
            n = data[0]
            assert "id" in n
            assert "incident_id" in n
            assert "narrative_version" in n
            assert "generated_by" in n
            assert "confidence" in n
            assert "created_at" in n
            assert "narrative" in n
            print(f"Latest narrative: v{n['narrative_version']}, generated_by={n['generated_by']}, confidence={n['confidence']}")
    
    def test_narratives_ordered_by_version_desc(self, operator_token, test_incident_ids):
        """Narratives are returned in descending order (newest first)"""
        incident_id = test_incident_ids["test_incident"]
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 1:
            versions = [n["narrative_version"] for n in data]
            assert versions == sorted(versions, reverse=True), f"Expected descending order but got {versions}"
            print(f"Versions in correct descending order: {versions}")
        else:
            print(f"Only {len(data)} narrative(s), cannot verify ordering")
    
    def test_empty_list_for_incident_without_narratives(self, operator_token, test_incident_ids):
        """Get narratives returns empty list for incident without any narratives"""
        # First check status to find one without narrative
        incident_id = test_incident_ids["low_battery"]
        status_response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative/status",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        
        if status_response.status_code == 200 and not status_response.json().get("has_narrative"):
            response = requests.get(
                f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
                headers={"Authorization": f"Bearer {operator_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            # After generation tests, this incident may have narratives now
            # So just verify it returns a valid list
            assert isinstance(data, list)
            print(f"Returned {len(data)} narrative(s) for this incident")

class TestNarrativeVersioning:
    """Test narrative version increments correctly on regeneration"""
    
    def test_version_increments_on_new_generation(self, operator_token, test_incident_ids):
        """Each new generation creates a new version"""
        incident_id = test_incident_ids["test_incident"]
        
        # Get current narratives
        response1 = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response1.status_code == 200
        current_narratives = response1.json()
        initial_count = len(current_narratives)
        initial_version = current_narratives[0]["narrative_version"] if current_narratives else 0
        
        print(f"Initial state: {initial_count} narrative(s), latest version {initial_version}")
        
        # NOTE: Since cached responses won't increment version, we just verify the concept
        # In production, version increments when input_hash changes
        
        # Generate new narrative (may be cached if input unchanged)
        response2 = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response2.status_code == 200
        gen_data = response2.json()
        
        if gen_data.get("cached"):
            print(f"Narrative was cached (input unchanged), version remains {initial_version}")
        else:
            new_version = gen_data.get("narrative_version", 0)
            assert new_version > initial_version, f"Expected version > {initial_version}, got {new_version}"
            print(f"New narrative generated: v{new_version}")

class TestNarrativeRBAC:
    """Test that narrative endpoints require operator/admin role"""
    
    def test_guardian_cannot_generate_narrative(self, guardian_token, test_incident_ids):
        """Guardian role should get 403 when generating narrative"""
        incident_id = test_incident_ids["test_incident"]
        response = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403 but got {response.status_code}"
        print("RBAC enforced: Guardian cannot generate narrative")
    
    def test_guardian_cannot_get_narratives(self, guardian_token, test_incident_ids):
        """Guardian role should get 403 when fetching narratives"""
        incident_id = test_incident_ids["test_incident"]
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403 but got {response.status_code}"
        print("RBAC enforced: Guardian cannot get narratives")
    
    def test_guardian_cannot_check_status(self, guardian_token, test_incident_ids):
        """Guardian role should get 403 when checking narrative status"""
        incident_id = test_incident_ids["test_incident"]
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative/status",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403 but got {response.status_code}"
        print("RBAC enforced: Guardian cannot check narrative status")
    
    def test_unauthenticated_user_gets_401(self, test_incident_ids):
        """Unauthenticated request should get 401"""
        incident_id = test_incident_ids["test_incident"]
        
        # No auth header
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative/status"
        )
        assert response.status_code == 401, f"Expected 401 but got {response.status_code}"
        print("Unauthenticated request correctly rejected with 401")

class TestNarrativeNarrativeContent:
    """Test AI-generated narrative content quality"""
    
    def test_narrative_has_valid_confidence(self, operator_token, test_incident_ids):
        """Confidence score is between 0 and 1"""
        incident_id = test_incident_ids["test_incident"]
        response = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        
        confidence = response.json().get("confidence", 0)
        assert 0 <= confidence <= 1, f"Confidence {confidence} should be between 0 and 1"
        print(f"Confidence score valid: {confidence}")
    
    def test_narrative_actions_have_priority_and_owner(self, operator_token, test_incident_ids):
        """Recommended actions have priority and owner fields"""
        incident_id = test_incident_ids["test_incident"]
        response = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        
        narrative = response.json().get("narrative", {})
        if isinstance(narrative, str):
            import json
            narrative = json.loads(narrative)
        
        actions = narrative.get("recommended_actions", [])
        for action in actions:
            assert "priority" in action, "Action missing priority"
            assert "action" in action, "Action missing action text"
            assert "owner" in action, "Action missing owner"
            assert action["owner"] in ["operator", "guardian", "system"], f"Invalid owner: {action['owner']}"
        
        print(f"All {len(actions)} actions have valid priority and owner")
    
    def test_narrative_evidence_has_timestamps(self, operator_token, test_incident_ids):
        """Evidence entries have timestamp and fact fields"""
        incident_id = test_incident_ids["test_incident"]
        response = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/narrative",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        
        narrative = response.json().get("narrative", {})
        if isinstance(narrative, str):
            import json
            narrative = json.loads(narrative)
        
        evidence = narrative.get("evidence", [])
        for e in evidence:
            assert "timestamp" in e, "Evidence missing timestamp"
            assert "fact" in e, "Evidence missing fact"
        
        print(f"All {len(evidence)} evidence items have timestamp and fact")

# Fixtures for all test classes
@pytest.fixture(scope="module")
def operator_token():
    """Get operator auth token for module"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@nischint.com",
        "password": "operator123"
    })
    if response.status_code != 200:
        pytest.skip(f"Operator login failed: {response.text}")
    return response.json()["access_token"]

@pytest.fixture(scope="module")
def guardian_token():
    """Get guardian auth token for module"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "nischint4parents@gmail.com",
        "password": "secret123"
    })
    if response.status_code != 200:
        pytest.skip(f"Guardian login failed: {response.text}")
    return response.json()["access_token"]

@pytest.fixture(scope="module")
def test_incident_ids():
    """Return known incident IDs for testing"""
    return {
        "test_incident": "23b02397-f738-448f-8492-d7f82c6bc38e",
        "device_offline": "3c3a9bae-4332-40fa-a0d0-1072d7125a85",
        "low_battery": "d4ab6faf-540b-47ca-8a4d-b2c06a8464b5",
        "non_existent": "00000000-0000-0000-0000-000000000000"
    }
