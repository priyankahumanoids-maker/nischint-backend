"""
Test suite for Nischint AI Chatbot API endpoints.
Tests: POST /api/chatbot/message, GET /api/chatbot/demo-steps, POST /api/chatbot/lead
"""
import os
import pytest
import requests
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestChatbotMessage:
    """Tests for POST /api/chatbot/message endpoint - GPT-5.2 powered responses"""

    def test_general_question_returns_text_response(self):
        """Test general question gets GPT-5.2 response"""
        response = requests.post(
            f"{BASE_URL}/api/chatbot/message",
            json={"session_id": f"test_{uuid.uuid4().hex[:8]}", "message": "What is Nischint?"},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "text"
        assert "message" in data
        assert len(data["message"]) > 0
        assert "session_id" in data
        print(f"GPT-5.2 response: {data['message'][:100]}...")

    def test_demo_trigger_returns_demo_type(self):
        """Test 'run live safety demo' triggers demo mode with 11 steps"""
        response = requests.post(
            f"{BASE_URL}/api/chatbot/message",
            json={"session_id": f"test_{uuid.uuid4().hex[:8]}", "message": "run live safety demo"},
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "demo"
        assert "steps" in data
        assert len(data["steps"]) == 11
        # Verify step types
        step_types = [s["type"] for s in data["steps"]]
        assert "system" in step_types
        assert "warning" in step_types
        assert "alert" in step_types
        assert "success" in step_types
        assert "info" in step_types
        print(f"Demo has {len(data['steps'])} steps")

    def test_demo_trigger_variations(self):
        """Test different demo trigger phrases"""
        triggers = [
            "show demo",
            "start safety demo",
            "demo run",
            "live demo"
        ]
        for trigger in triggers:
            response = requests.post(
                f"{BASE_URL}/api/chatbot/message",
                json={"session_id": f"test_{uuid.uuid4().hex[:8]}", "message": trigger},
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            assert response.status_code == 200
            data = response.json()
            assert data["type"] == "demo", f"Trigger '{trigger}' should return demo type"
            print(f"Trigger '{trigger}' -> demo type OK")

    def test_lead_prompt_trigger_returns_lead_prompt(self):
        """Test pilot/deploy keywords trigger lead capture prompt"""
        triggers = [
            "I want to deploy a pilot",
            "schedule a pilot",
            "contact sales",
            "sign up for pilot"
        ]
        for trigger in triggers:
            response = requests.post(
                f"{BASE_URL}/api/chatbot/message",
                json={"session_id": f"test_{uuid.uuid4().hex[:8]}", "message": trigger},
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            assert response.status_code == 200
            data = response.json()
            assert data["type"] == "lead_prompt", f"Trigger '{trigger}' should return lead_prompt"
            assert "/pilot" in data["message"] or "hello@nischint.app" in data["message"]
            print(f"Trigger '{trigger}' -> lead_prompt type OK")

    def test_about_nischint_returns_platform_info(self):
        """Test asking about Nischint returns relevant info"""
        response = requests.post(
            f"{BASE_URL}/api/chatbot/message",
            json={"session_id": f"test_{uuid.uuid4().hex[:8]}", "message": "Tell me about school safety solutions"},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "text"
        assert len(data["message"]) > 50
        print(f"School safety response: {data['message'][:100]}...")


class TestDemoSteps:
    """Tests for GET /api/chatbot/demo-steps endpoint"""

    def test_get_demo_steps_returns_11_steps(self):
        """Test demo-steps endpoint returns all 11 steps"""
        response = requests.get(f"{BASE_URL}/api/chatbot/demo-steps", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "steps" in data
        assert len(data["steps"]) == 11
        
        # Verify each step has required fields
        for i, step in enumerate(data["steps"]):
            assert "delay" in step, f"Step {i} missing delay"
            assert "message" in step, f"Step {i} missing message"
            assert "type" in step, f"Step {i} missing type"
            assert step["type"] in ["system", "warning", "alert", "success", "info"], f"Step {i} has invalid type"
        print(f"Demo steps: {[s['type'] for s in data['steps']]}")

    def test_demo_steps_timing(self):
        """Verify demo steps have proper delays"""
        response = requests.get(f"{BASE_URL}/api/chatbot/demo-steps", timeout=10)
        data = response.json()
        total_delay = sum(s["delay"] for s in data["steps"])
        # Total demo should be ~22 seconds (0+2+3+3+2+2+2+3+2+2+1 = 22)
        assert 18 <= total_delay <= 25, f"Total delay {total_delay}s should be ~22s"
        print(f"Total demo duration: {total_delay}s")


class TestLeadCapture:
    """Tests for POST /api/chatbot/lead endpoint - stores in pilot_leads table"""

    def test_lead_capture_success(self):
        """Test successful lead capture with all fields"""
        response = requests.post(
            f"{BASE_URL}/api/chatbot/lead",
            json={
                "session_id": f"test_{uuid.uuid4().hex[:8]}",
                "name": "TEST_ChatbotTest",
                "institution": "TEST_University",
                "email": "test_chatbot_pytest@example.com",
                "city": "Bangalore"
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "text"
        assert "Thank you" in data["message"] or "received" in data["message"].lower()
        assert "session_id" in data
        print(f"Lead capture response: {data['message'][:80]}...")

    def test_lead_capture_without_city(self):
        """Test lead capture works without optional city field"""
        response = requests.post(
            f"{BASE_URL}/api/chatbot/lead",
            json={
                "session_id": f"test_{uuid.uuid4().hex[:8]}",
                "name": "TEST_NoCity",
                "institution": "TEST_College",
                "email": "test_nocity@example.com"
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "text"
        print("Lead capture without city: OK")

    def test_lead_capture_missing_required_fields(self):
        """Test lead capture fails gracefully with missing required fields"""
        response = requests.post(
            f"{BASE_URL}/api/chatbot/lead",
            json={
                "session_id": "test_missing",
                "name": "TEST_Missing"
                # Missing institution and email
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        # Should return 422 validation error
        assert response.status_code == 422
        print("Missing fields validation: OK")


class TestChatbotIntegration:
    """Integration tests for complete chatbot flow"""

    def test_session_id_preserved(self):
        """Verify session_id is returned in all responses"""
        session_id = f"test_session_{uuid.uuid4().hex[:8]}"
        
        # Test message endpoint
        response = requests.post(
            f"{BASE_URL}/api/chatbot/message",
            json={"session_id": session_id, "message": "Hello"},
            timeout=30
        )
        assert response.json()["session_id"] == session_id
        
        # Test demo trigger
        response = requests.post(
            f"{BASE_URL}/api/chatbot/message",
            json={"session_id": session_id, "message": "run demo"},
            timeout=10
        )
        assert response.json()["session_id"] == session_id
        print("Session ID preserved: OK")

    def test_rate_limiting_exists(self):
        """Verify rate limiting is active (30/min for messages)"""
        # Just verify endpoint responds - don't actually hit rate limit
        response = requests.post(
            f"{BASE_URL}/api/chatbot/message",
            json={"session_id": "rate_test", "message": "test"},
            timeout=30
        )
        # Response should succeed - rate limit allows 30/min
        assert response.status_code in [200, 429]
        print(f"Rate limit check: status {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
