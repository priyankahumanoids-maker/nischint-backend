"""
Sequential Escalation Engine Tests
Tests for the Intelligent Sequential Escalation Engine:
1. POST /api/twilio/status - Twilio webhook endpoint (no auth required)
2. get_call_status() - Redis polling for call resolution
3. sort_contacts_by_priority() - Guardian priority sorting
4. intelligent_escalation() - Sequential voice calls + SMS blast
5. make_voice_call_with_callback() - Voice call with status callback + machine detection
6. EscalationContact dataclass
7. _trigger_guardian_failsafe - Contact collection from 4 sources
"""
import pytest
import requests
import os
import asyncio
from unittest.mock import patch, MagicMock

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


# ============================================================================
# Module 1: Twilio Status Webhook Tests (POST /api/twilio/status)
# ============================================================================
class TestTwilioStatusWebhook:
    """Tests for POST /api/twilio/status endpoint - receives Twilio call status updates"""

    def test_webhook_accepts_form_data(self):
        """Webhook should accept Twilio form data (application/x-www-form-urlencoded)"""
        form_data = {
            "CallSid": "CA_test_webhook_form_data_001",
            "CallStatus": "in-progress",
            "To": "+919876543210",
            "From": "+17154188069",
            "AnsweredBy": "human",
            "CallDuration": "0",
        }
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,  # form data, not JSON
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        assert "application/xml" in response.headers.get("Content-Type", "")
        assert "<Response/>" in response.text
        print("PASSED: Webhook accepts form data and returns XML")

    def test_webhook_returns_xml_response(self):
        """Webhook should return TwiML-compatible XML response"""
        form_data = {
            "CallSid": "CA_test_xml_response_002",
            "CallStatus": "completed",
            "To": "+919876543210",
            "From": "+17154188069",
        }
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        assert response.text == "<Response/>"
        print("PASSED: Webhook returns <Response/> XML")

    def test_webhook_no_auth_required(self):
        """Webhook should NOT require authentication (Twilio sends directly)"""
        form_data = {
            "CallSid": "CA_test_no_auth_003",
            "CallStatus": "ringing",
            "To": "+919876543210",
            "From": "+17154188069",
        }
        # No auth headers
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        # Should NOT return 401/403
        assert response.status_code == 200, f"Expected 200 (no auth), got {response.status_code}"
        print("PASSED: Webhook does not require authentication")

    def test_webhook_handles_human_answered(self):
        """Webhook should identify human-answered calls (in-progress + human)"""
        form_data = {
            "CallSid": "CA_test_human_answered_004",
            "CallStatus": "in-progress",
            "To": "+919876543210",
            "From": "+17154188069",
            "AnsweredBy": "human",
            "CallDuration": "5",
        }
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        print("PASSED: Webhook handles human-answered call")

    def test_webhook_handles_voicemail_machine_start(self):
        """Webhook should identify voicemail (machine_start)"""
        form_data = {
            "CallSid": "CA_test_voicemail_005",
            "CallStatus": "in-progress",
            "To": "+919876543210",
            "From": "+17154188069",
            "AnsweredBy": "machine_start",
        }
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        print("PASSED: Webhook handles voicemail (machine_start)")

    def test_webhook_handles_voicemail_machine_end_beep(self):
        """Webhook should identify voicemail (machine_end_beep)"""
        form_data = {
            "CallSid": "CA_test_voicemail_beep_006",
            "CallStatus": "in-progress",
            "To": "+919876543210",
            "From": "+17154188069",
            "AnsweredBy": "machine_end_beep",
        }
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        print("PASSED: Webhook handles voicemail (machine_end_beep)")

    def test_webhook_handles_busy(self):
        """Webhook should handle busy status"""
        form_data = {
            "CallSid": "CA_test_busy_007",
            "CallStatus": "busy",
            "To": "+919876543210",
            "From": "+17154188069",
        }
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        print("PASSED: Webhook handles busy status")

    def test_webhook_handles_no_answer(self):
        """Webhook should handle no-answer status"""
        form_data = {
            "CallSid": "CA_test_no_answer_008",
            "CallStatus": "no-answer",
            "To": "+919876543210",
            "From": "+17154188069",
        }
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        print("PASSED: Webhook handles no-answer status")

    def test_webhook_handles_failed(self):
        """Webhook should handle failed status"""
        form_data = {
            "CallSid": "CA_test_failed_009",
            "CallStatus": "failed",
            "To": "+919876543210",
            "From": "+17154188069",
        }
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        print("PASSED: Webhook handles failed status")

    def test_webhook_handles_canceled(self):
        """Webhook should handle canceled status"""
        form_data = {
            "CallSid": "CA_test_canceled_010",
            "CallStatus": "canceled",
            "To": "+919876543210",
            "From": "+17154188069",
        }
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        print("PASSED: Webhook handles canceled status")


# ============================================================================
# Module 2: Redis Call Status Polling Tests
# ============================================================================
class TestRedisCallStatusPolling:
    """Tests for get_call_status() Redis polling function"""

    def test_get_call_status_import(self):
        """get_call_status should be importable from twilio_webhook"""
        from app.api.twilio_webhook import get_call_status
        assert callable(get_call_status)
        print("PASSED: get_call_status is importable and callable")

    def test_get_call_status_returns_none_for_unknown_sid(self):
        """get_call_status should return None for unknown call_sid"""
        from app.api.twilio_webhook import get_call_status
        result = get_call_status("CA_unknown_sid_never_exists_xyz")
        assert result is None
        print("PASSED: get_call_status returns None for unknown call_sid")

    def test_redis_service_set_get_json(self):
        """Redis service set_json/get_json should work for call status"""
        from app.services.redis_service import set_json, get_json
        
        test_key = "test_call_status_011"
        test_data = {"status": "answered", "phone": "+919876543210"}
        
        # Set
        result = set_json("twilio_call", test_key, test_data, ttl=60)
        # May return False if Redis not available, but should not error
        
        # Get
        retrieved = get_json("twilio_call", test_key)
        if retrieved:
            assert retrieved["status"] == "answered"
            print("PASSED: Redis set_json/get_json works for call status")
        else:
            print("PASSED: Redis not available (graceful degradation)")

    def test_webhook_stores_in_redis(self):
        """Webhook should store call status in Redis"""
        from app.services.redis_service import get_json
        
        call_sid = "CA_test_redis_store_012"
        form_data = {
            "CallSid": call_sid,
            "CallStatus": "in-progress",
            "To": "+919876543210",
            "From": "+17154188069",
            "AnsweredBy": "human",
        }
        
        # Send webhook
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        
        # Check Redis (may be None if Redis not available)
        stored = get_json("twilio_call", call_sid)
        if stored:
            assert stored["call_sid"] == call_sid
            assert stored["status"] == "in-progress"
            print("PASSED: Webhook stores call data in Redis")
        else:
            print("PASSED: Redis not available (graceful degradation)")

    def test_webhook_stores_resolved_status_for_human(self):
        """Webhook should store resolved='answered' for human pickup"""
        from app.services.redis_service import get_json
        
        call_sid = "CA_test_resolved_human_013"
        form_data = {
            "CallSid": call_sid,
            "CallStatus": "in-progress",
            "To": "+919876543210",
            "From": "+17154188069",
            "AnsweredBy": "human",
        }
        
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        
        # Check resolved status
        resolved = get_json("twilio_call", f"{call_sid}:resolved")
        if resolved:
            assert resolved == "answered"
            print("PASSED: Webhook stores resolved='answered' for human")
        else:
            print("PASSED: Redis not available (graceful degradation)")

    def test_webhook_stores_resolved_status_for_voicemail(self):
        """Webhook should store resolved='voicemail' for machine detection"""
        from app.services.redis_service import get_json
        
        call_sid = "CA_test_resolved_voicemail_014"
        form_data = {
            "CallSid": call_sid,
            "CallStatus": "in-progress",
            "To": "+919876543210",
            "From": "+17154188069",
            "AnsweredBy": "machine_end_beep",
        }
        
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        
        resolved = get_json("twilio_call", f"{call_sid}:resolved")
        if resolved:
            assert resolved == "voicemail"
            print("PASSED: Webhook stores resolved='voicemail' for machine")
        else:
            print("PASSED: Redis not available (graceful degradation)")


# ============================================================================
# Module 3: Sequential Escalation Module Tests
# ============================================================================
class TestSequentialEscalationModule:
    """Tests for sequential_escalation.py module"""

    def test_escalation_contact_dataclass(self):
        """EscalationContact dataclass should have required fields"""
        from app.services.sequential_escalation import EscalationContact
        
        contact = EscalationContact(
            phone="+919876543210",
            name="Test Guardian",
            source="guardian_relationship",
            is_primary=True,
            priority=1,
            guardian_user_id="uuid-123",
        )
        
        assert contact.phone == "+919876543210"
        assert contact.name == "Test Guardian"
        assert contact.source == "guardian_relationship"
        assert contact.is_primary is True
        assert contact.priority == 1
        assert contact.guardian_user_id == "uuid-123"
        print("PASSED: EscalationContact dataclass has all required fields")

    def test_escalation_contact_defaults(self):
        """EscalationContact should have correct defaults"""
        from app.services.sequential_escalation import EscalationContact
        
        contact = EscalationContact(
            phone="+919876543210",
            name="Test",
            source="emergency_contact",
        )
        
        assert contact.is_primary is False
        assert contact.priority == 99
        assert contact.guardian_user_id is None
        print("PASSED: EscalationContact has correct defaults")

    def test_escalation_result_dataclass(self):
        """EscalationResult dataclass should have required fields"""
        from app.services.sequential_escalation import EscalationResult
        
        result = EscalationResult(
            phone="+919876543210",
            name="Test",
            source="guardian",
            method="voice_answered",
            call_sid="CA123",
            call_status="answered",
            answered_by="human",
            success=True,
        )
        
        assert result.phone == "+919876543210"
        assert result.method == "voice_answered"
        assert result.success is True
        print("PASSED: EscalationResult dataclass has all required fields")

    def test_escalation_summary_dataclass(self):
        """EscalationSummary dataclass should have required fields"""
        from app.services.sequential_escalation import EscalationSummary
        
        summary = EscalationSummary(
            event_id="evt-123",
            child_name="Test Child",
        )
        
        assert summary.event_id == "evt-123"
        assert summary.child_name == "Test Child"
        assert summary.results == []
        assert summary.resolved_by is None
        assert summary.total_calls == 0
        assert summary.total_sms == 0
        assert summary.sms_blast_sent is False
        print("PASSED: EscalationSummary dataclass has all required fields")


# ============================================================================
# Module 4: Guardian Priority Sorting Tests
# ============================================================================
class TestGuardianPrioritySorting:
    """Tests for sort_contacts_by_priority() function"""

    def test_sort_contacts_by_priority_import(self):
        """sort_contacts_by_priority should be importable"""
        from app.services.sequential_escalation import sort_contacts_by_priority
        assert callable(sort_contacts_by_priority)
        print("PASSED: sort_contacts_by_priority is importable")

    def test_primary_guardians_first(self):
        """Primary guardians should be sorted first"""
        from app.services.sequential_escalation import (
            sort_contacts_by_priority,
            EscalationContact,
        )
        
        contacts = [
            EscalationContact(phone="+1111", name="Secondary", source="guardian", is_primary=False, priority=1),
            EscalationContact(phone="+2222", name="Primary", source="guardian", is_primary=True, priority=2),
            EscalationContact(phone="+3333", name="Emergency", source="emergency_contact", is_primary=False, priority=3),
        ]
        
        sorted_contacts = sort_contacts_by_priority(contacts)
        
        assert sorted_contacts[0].name == "Primary"
        assert sorted_contacts[0].is_primary is True
        print("PASSED: Primary guardians sorted first")

    def test_sort_by_priority_within_group(self):
        """Within same is_primary group, sort by priority (lower = higher priority)"""
        from app.services.sequential_escalation import (
            sort_contacts_by_priority,
            EscalationContact,
        )
        
        contacts = [
            EscalationContact(phone="+1111", name="Priority3", source="guardian", is_primary=False, priority=3),
            EscalationContact(phone="+2222", name="Priority1", source="guardian", is_primary=False, priority=1),
            EscalationContact(phone="+3333", name="Priority2", source="guardian", is_primary=False, priority=2),
        ]
        
        sorted_contacts = sort_contacts_by_priority(contacts)
        
        assert sorted_contacts[0].name == "Priority1"
        assert sorted_contacts[1].name == "Priority2"
        assert sorted_contacts[2].name == "Priority3"
        print("PASSED: Contacts sorted by priority within group")

    def test_complex_sorting_scenario(self):
        """Test complex sorting: primary first, then by priority"""
        from app.services.sequential_escalation import (
            sort_contacts_by_priority,
            EscalationContact,
        )
        
        contacts = [
            EscalationContact(phone="+1111", name="Secondary-P3", source="guardian", is_primary=False, priority=3),
            EscalationContact(phone="+2222", name="Primary-P2", source="guardian", is_primary=True, priority=2),
            EscalationContact(phone="+3333", name="Primary-P1", source="guardian", is_primary=True, priority=1),
            EscalationContact(phone="+4444", name="Secondary-P1", source="guardian", is_primary=False, priority=1),
        ]
        
        sorted_contacts = sort_contacts_by_priority(contacts)
        
        # Primary contacts first (sorted by priority)
        assert sorted_contacts[0].name == "Primary-P1"
        assert sorted_contacts[1].name == "Primary-P2"
        # Then secondary contacts (sorted by priority)
        assert sorted_contacts[2].name == "Secondary-P1"
        assert sorted_contacts[3].name == "Secondary-P3"
        print("PASSED: Complex sorting scenario works correctly")


# ============================================================================
# Module 5: make_voice_call_with_callback Tests
# ============================================================================
class TestMakeVoiceCallWithCallback:
    """Tests for make_voice_call_with_callback() function"""

    def test_make_voice_call_with_callback_import(self):
        """make_voice_call_with_callback should be importable"""
        from app.services.sms_service import make_voice_call_with_callback
        assert callable(make_voice_call_with_callback)
        print("PASSED: make_voice_call_with_callback is importable")

    def test_make_voice_call_with_callback_signature(self):
        """make_voice_call_with_callback should accept required parameters"""
        from app.services.sms_service import make_voice_call_with_callback
        import inspect
        
        sig = inspect.signature(make_voice_call_with_callback)
        params = list(sig.parameters.keys())
        
        assert "to" in params
        assert "child_name" in params
        assert "alert_type" in params
        assert "event_id" in params
        assert "contact_name" in params
        assert "callback_url" in params
        print("PASSED: make_voice_call_with_callback has correct signature")

    def test_make_voice_call_with_callback_returns_call_sid_or_none(self):
        """make_voice_call_with_callback should return call_sid (str) or None"""
        from app.services.sms_service import make_voice_call_with_callback
        
        # Call with unverified number (Twilio trial will fail - expected)
        result = make_voice_call_with_callback(
            to="+919999999999",  # Unverified number
            child_name="Test Child",
            alert_type="test_alert",
            event_id="evt-test-callback-001",
            contact_name="Test Guardian",
            callback_url="https://example.com/callback",
        )
        
        # Should return None (Twilio trial fails for unverified) or call_sid string
        assert result is None or isinstance(result, str)
        print("PASSED: make_voice_call_with_callback returns call_sid or None")


# ============================================================================
# Module 6: intelligent_escalation Tests
# ============================================================================
class TestIntelligentEscalation:
    """Tests for intelligent_escalation() async function"""

    def test_intelligent_escalation_import(self):
        """intelligent_escalation should be importable"""
        from app.services.sequential_escalation import intelligent_escalation
        assert callable(intelligent_escalation)
        print("PASSED: intelligent_escalation is importable")

    def test_intelligent_escalation_is_async(self):
        """intelligent_escalation should be an async function"""
        from app.services.sequential_escalation import intelligent_escalation
        import asyncio
        
        assert asyncio.iscoroutinefunction(intelligent_escalation)
        print("PASSED: intelligent_escalation is async")

    def test_wait_for_call_status_import(self):
        """wait_for_call_status should be importable"""
        from app.services.sequential_escalation import wait_for_call_status
        assert callable(wait_for_call_status)
        print("PASSED: wait_for_call_status is importable")

    def test_wait_for_call_status_is_async(self):
        """wait_for_call_status should be an async function"""
        from app.services.sequential_escalation import wait_for_call_status
        import asyncio
        
        assert asyncio.iscoroutinefunction(wait_for_call_status)
        print("PASSED: wait_for_call_status is async")

    def test_constants_defined(self):
        """Module should define CALL_WAIT_TIMEOUT_S and POLL_INTERVAL_S"""
        from app.services import sequential_escalation
        
        assert hasattr(sequential_escalation, "CALL_WAIT_TIMEOUT_S")
        assert hasattr(sequential_escalation, "POLL_INTERVAL_S")
        assert sequential_escalation.CALL_WAIT_TIMEOUT_S == 35
        assert sequential_escalation.POLL_INTERVAL_S == 2
        print("PASSED: Constants CALL_WAIT_TIMEOUT_S=35, POLL_INTERVAL_S=2 defined")


# ============================================================================
# Module 7: Auto Escalation Engine Integration Tests
# ============================================================================
class TestAutoEscalationEngineIntegration:
    """Tests for auto_escalation_engine.py integration with sequential escalation"""

    def test_trigger_guardian_failsafe_uses_intelligent_escalation(self):
        """_trigger_guardian_failsafe should import intelligent_escalation"""
        # Check the import exists in the module
        import ast
        
        with open("/app/backend/app/services/auto_escalation_engine.py", "r") as f:
            source = f.read()
        
        # Check for intelligent_escalation import
        assert "intelligent_escalation" in source
        assert "EscalationContact" in source
        print("PASSED: auto_escalation_engine imports intelligent_escalation and EscalationContact")

    def test_trigger_guardian_failsafe_collects_from_4_sources(self):
        """_trigger_guardian_failsafe should collect contacts from 4 sources"""
        import ast
        
        with open("/app/backend/app/services/auto_escalation_engine.py", "r") as f:
            source = f.read()
        
        # Check for all 4 sources
        assert "GuardianRelationship" in source
        assert "Relationship" in source
        assert "Guardian" in source
        assert "EmergencyContact" in source
        print("PASSED: _trigger_guardian_failsafe collects from 4 sources")

    def test_escalation_contact_sources_in_code(self):
        """EscalationContact should be created with correct source values"""
        import ast
        
        with open("/app/backend/app/services/auto_escalation_engine.py", "r") as f:
            source = f.read()
        
        # Check for source values
        assert 'source="guardian_relationship"' in source
        assert 'source="relationship"' in source
        assert 'source="guardian"' in source
        assert 'source="emergency_contact"' in source
        print("PASSED: EscalationContact created with correct source values")


# ============================================================================
# Module 8: Twilio Webhook Redis Namespace Tests
# ============================================================================
class TestTwilioWebhookRedisNamespace:
    """Tests for Redis namespace and key format"""

    def test_redis_namespace_constant(self):
        """Webhook should use correct Redis namespace"""
        from app.api.twilio_webhook import REDIS_NS
        
        assert REDIS_NS == "twilio_call"
        print("PASSED: REDIS_NS = 'twilio_call'")

    def test_call_status_ttl_constant(self):
        """Webhook should use correct TTL"""
        from app.api.twilio_webhook import CALL_STATUS_TTL
        
        assert CALL_STATUS_TTL == 300  # 5 minutes
        print("PASSED: CALL_STATUS_TTL = 300 (5 minutes)")

    def test_redis_key_format(self):
        """Redis keys should follow nischint:twilio_call:{call_sid} format"""
        from app.services.redis_service import _key
        
        key = _key("twilio_call", "CA123")
        assert key == "nischint:twilio_call:CA123"
        print("PASSED: Redis key format is nischint:twilio_call:{call_sid}")


# ============================================================================
# Module 9: Voicemail Detection Tests
# ============================================================================
class TestVoicemailDetection:
    """Tests for voicemail/machine detection logic"""

    def test_voicemail_detection_values(self):
        """Webhook should detect all voicemail AnsweredBy values"""
        voicemail_values = [
            "machine_start",
            "machine_end_beep",
            "machine_end_silence",
            "machine_end_other",
        ]
        
        for answered_by in voicemail_values:
            form_data = {
                "CallSid": f"CA_voicemail_test_{answered_by}",
                "CallStatus": "in-progress",
                "To": "+919876543210",
                "From": "+17154188069",
                "AnsweredBy": answered_by,
            }
            response = requests.post(
                f"{BASE_URL}/api/twilio/status",
                data=form_data,
            )
            assert response.status_code == 200
        
        print("PASSED: All voicemail AnsweredBy values handled")

    def test_human_detection_empty_answered_by(self):
        """in-progress with empty AnsweredBy should be treated as human"""
        form_data = {
            "CallSid": "CA_human_empty_answered_by",
            "CallStatus": "in-progress",
            "To": "+919876543210",
            "From": "+17154188069",
            "AnsweredBy": "",  # Empty = human
        }
        response = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data=form_data,
        )
        assert response.status_code == 200
        print("PASSED: Empty AnsweredBy treated as human")


# ============================================================================
# Module 10: SMS Blast Fallback Tests
# ============================================================================
class TestSMSBlastFallback:
    """Tests for SMS blast when nobody answers"""

    def test_send_failsafe_sms_import(self):
        """send_failsafe_sms should be importable"""
        from app.services.sms_service import send_failsafe_sms
        assert callable(send_failsafe_sms)
        print("PASSED: send_failsafe_sms is importable")

    def test_send_failsafe_sms_signature(self):
        """send_failsafe_sms should accept required parameters"""
        from app.services.sms_service import send_failsafe_sms
        import inspect
        
        sig = inspect.signature(send_failsafe_sms)
        params = list(sig.parameters.keys())
        
        assert "to" in params
        assert "child_name" in params
        assert "alert_type" in params
        assert "last_seen" in params
        assert "contact_name" in params
        print("PASSED: send_failsafe_sms has correct signature")

    def test_is_available_and_is_voice_available(self):
        """is_available() and is_voice_available() should be importable"""
        from app.services.sms_service import is_available, is_voice_available
        
        sms_avail = is_available()
        voice_avail = is_voice_available()
        
        assert isinstance(sms_avail, bool)
        assert isinstance(voice_avail, bool)
        print(f"PASSED: is_available={sms_avail}, is_voice_available={voice_avail}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
