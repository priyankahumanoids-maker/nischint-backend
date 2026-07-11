"""
SSE Escalation Emission Tests
=============================
Tests for the real-time escalation visibility system:
1. POST /api/twilio/status webhook stores correct call statuses in Redis
2. emit_escalation_event() broadcasts to guardians + operators
3. broadcast_escalation_update() in event_broadcaster.py
4. intelligent_escalation() accepts guardian_ids parameter
5. Priority sorting: primary guardians first, then by priority
6. Sequential chain stops when human answers
7. SMS blast fires when all contacts exhausted
8. auto_escalation_engine collects guardian_ids and passes to intelligent_escalation
"""
import pytest
import requests
import os
import asyncio
import inspect
from unittest.mock import patch, AsyncMock, MagicMock

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://gps-mic-restart.preview.emergentagent.com").rstrip("/")


def run_async(coro):
    """Helper to run async code in sync tests"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 1: Twilio Status Webhook - Redis Storage
# ═══════════════════════════════════════════════════════════════
class TestTwilioStatusWebhookRedisStorage:
    """POST /api/twilio/status webhook stores correct call statuses in Redis"""

    def test_webhook_stores_answered_status(self):
        """Human answered call stores 'answered' in Redis"""
        resp = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data={
                "CallSid": "CA_test_answered_001",
                "CallStatus": "in-progress",
                "To": "+919999999999",
                "From": "+1234567890",
                "AnsweredBy": "human",
                "CallDuration": "0",
            },
        )
        assert resp.status_code == 200
        assert "<Response/>" in resp.text
        
        # Verify Redis storage
        from app.api.twilio_webhook import get_call_status
        status = get_call_status("CA_test_answered_001")
        assert status == "answered", f"Expected 'answered', got '{status}'"

    def test_webhook_stores_voicemail_status(self):
        """Voicemail detection stores 'voicemail' in Redis"""
        resp = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data={
                "CallSid": "CA_test_voicemail_001",
                "CallStatus": "in-progress",
                "To": "+919999999999",
                "From": "+1234567890",
                "AnsweredBy": "machine_start",
                "CallDuration": "0",
            },
        )
        assert resp.status_code == 200
        
        from app.api.twilio_webhook import get_call_status
        status = get_call_status("CA_test_voicemail_001")
        assert status == "voicemail", f"Expected 'voicemail', got '{status}'"

    def test_webhook_stores_busy_status(self):
        """Busy call stores 'busy' in Redis"""
        resp = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data={
                "CallSid": "CA_test_busy_001",
                "CallStatus": "busy",
                "To": "+919999999999",
                "From": "+1234567890",
                "AnsweredBy": "",
                "CallDuration": "0",
            },
        )
        assert resp.status_code == 200
        
        from app.api.twilio_webhook import get_call_status
        status = get_call_status("CA_test_busy_001")
        assert status == "busy", f"Expected 'busy', got '{status}'"

    def test_webhook_stores_no_answer_status(self):
        """No-answer call stores 'no-answer' in Redis"""
        resp = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data={
                "CallSid": "CA_test_noanswer_001",
                "CallStatus": "no-answer",
                "To": "+919999999999",
                "From": "+1234567890",
                "AnsweredBy": "",
                "CallDuration": "0",
            },
        )
        assert resp.status_code == 200
        
        from app.api.twilio_webhook import get_call_status
        status = get_call_status("CA_test_noanswer_001")
        assert status == "no-answer", f"Expected 'no-answer', got '{status}'"

    def test_webhook_stores_failed_status(self):
        """Failed call stores 'failed' in Redis"""
        resp = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data={
                "CallSid": "CA_test_failed_001",
                "CallStatus": "failed",
                "To": "+919999999999",
                "From": "+1234567890",
                "AnsweredBy": "",
                "CallDuration": "0",
            },
        )
        assert resp.status_code == 200
        
        from app.api.twilio_webhook import get_call_status
        status = get_call_status("CA_test_failed_001")
        assert status == "failed", f"Expected 'failed', got '{status}'"

    def test_webhook_stores_canceled_status(self):
        """Canceled call stores 'canceled' in Redis"""
        resp = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data={
                "CallSid": "CA_test_canceled_001",
                "CallStatus": "canceled",
                "To": "+919999999999",
                "From": "+1234567890",
                "AnsweredBy": "",
                "CallDuration": "0",
            },
        )
        assert resp.status_code == 200
        
        from app.api.twilio_webhook import get_call_status
        status = get_call_status("CA_test_canceled_001")
        assert status == "canceled", f"Expected 'canceled', got '{status}'"

    def test_webhook_returns_xml_response(self):
        """Webhook returns TwiML-compatible XML response"""
        resp = requests.post(
            f"{BASE_URL}/api/twilio/status",
            data={
                "CallSid": "CA_test_xml_001",
                "CallStatus": "completed",
                "To": "+919999999999",
                "From": "+1234567890",
                "AnsweredBy": "",
                "CallDuration": "30",
            },
        )
        assert resp.status_code == 200
        assert "application/xml" in resp.headers.get("content-type", "")
        assert "<Response/>" in resp.text


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 2: emit_escalation_event() Function
# ═══════════════════════════════════════════════════════════════
class TestEmitEscalationEvent:
    """emit_escalation_event() broadcasts to guardians + operators"""

    def test_emit_escalation_event_exists(self):
        """emit_escalation_event function exists and is async"""
        from app.services.sequential_escalation import emit_escalation_event
        assert callable(emit_escalation_event)
        assert asyncio.iscoroutinefunction(emit_escalation_event)

    def test_emit_escalation_event_signature(self):
        """emit_escalation_event has correct parameters"""
        from app.services.sequential_escalation import emit_escalation_event
        sig = inspect.signature(emit_escalation_event)
        params = list(sig.parameters.keys())
        
        assert "guardian_ids" in params
        assert "event_id" in params
        assert "child_name" in params
        assert "status" in params
        assert "current_guardian" in params
        assert "sequence" in params
        assert "total_guardians" in params
        assert "resolved_by" in params

    def test_emit_escalation_event_calls_broadcaster(self):
        """emit_escalation_event calls broadcast_escalation_update"""
        from app.services.sequential_escalation import emit_escalation_event
        
        async def run_test():
            with patch("app.services.event_broadcaster.broadcaster.broadcast_escalation_update", new_callable=AsyncMock) as mock_broadcast:
                await emit_escalation_event(
                    guardian_ids=["guardian-1", "guardian-2"],
                    event_id="test-event-001",
                    child_name="TestChild",
                    status="calling",
                    current_guardian={"name": "Mom", "phone": "+91999"},
                    sequence=1,
                    total_guardians=3,
                )
                
                mock_broadcast.assert_called_once()
                call_args = mock_broadcast.call_args
                assert call_args[0][0] == ["guardian-1", "guardian-2"]  # guardian_ids
                payload = call_args[0][1]
                assert payload["event_id"] == "test-event-001"
                assert payload["child_name"] == "TestChild"
                assert payload["status"] == "calling"
                assert payload["sequence"] == 1
                assert payload["total_guardians"] == 3
        
        run_async(run_test())


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 3: broadcast_escalation_update() in EventBroadcaster
# ═══════════════════════════════════════════════════════════════
class TestBroadcastEscalationUpdate:
    """broadcast_escalation_update() method in event_broadcaster.py"""

    def test_broadcast_escalation_update_exists(self):
        """broadcast_escalation_update method exists"""
        from app.services.event_broadcaster import broadcaster
        assert hasattr(broadcaster, "broadcast_escalation_update")
        assert callable(broadcaster.broadcast_escalation_update)

    def test_broadcast_escalation_update_is_async(self):
        """broadcast_escalation_update is async"""
        from app.services.event_broadcaster import broadcaster
        assert asyncio.iscoroutinefunction(broadcaster.broadcast_escalation_update)

    def test_broadcast_escalation_update_broadcasts_to_guardians(self):
        """broadcast_escalation_update sends to all guardian channels"""
        from app.services.event_broadcaster import broadcaster
        
        async def run_test():
            with patch.object(broadcaster, "broadcast_to_user", new_callable=AsyncMock) as mock_user:
                with patch.object(broadcaster, "broadcast_to_operators", new_callable=AsyncMock) as mock_ops:
                    await broadcaster.broadcast_escalation_update(
                        guardian_ids=["g1", "g2", "g3"],
                        payload={"status": "calling", "child_name": "Test"}
                    )
                    
                    # Should call broadcast_to_user for each guardian
                    assert mock_user.call_count == 3
                    
                    # Should call broadcast_to_operators once
                    mock_ops.assert_called_once()
                    
                    # Verify event type is escalation_update
                    for call in mock_user.call_args_list:
                        assert call[0][1] == "escalation_update"
        
        run_async(run_test())

    def test_broadcast_escalation_update_sends_to_operators(self):
        """broadcast_escalation_update sends to operator channel"""
        from app.services.event_broadcaster import broadcaster
        
        async def run_test():
            with patch.object(broadcaster, "broadcast_to_user", new_callable=AsyncMock):
                with patch.object(broadcaster, "broadcast_to_operators", new_callable=AsyncMock) as mock_ops:
                    await broadcaster.broadcast_escalation_update(
                        guardian_ids=["g1"],
                        payload={"status": "answered", "resolved_by": "Mom"}
                    )
                    
                    mock_ops.assert_called_once_with("escalation_update", {"status": "answered", "resolved_by": "Mom"})
        
        run_async(run_test())


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 4: intelligent_escalation() guardian_ids Parameter
# ═══════════════════════════════════════════════════════════════
class TestIntelligentEscalationGuardianIds:
    """intelligent_escalation() accepts guardian_ids parameter"""

    def test_intelligent_escalation_has_guardian_ids_param(self):
        """intelligent_escalation has guardian_ids parameter"""
        from app.services.sequential_escalation import intelligent_escalation
        sig = inspect.signature(intelligent_escalation)
        params = list(sig.parameters.keys())
        
        assert "guardian_ids" in params

    def test_intelligent_escalation_guardian_ids_default_none(self):
        """guardian_ids defaults to None"""
        from app.services.sequential_escalation import intelligent_escalation
        sig = inspect.signature(intelligent_escalation)
        
        guardian_ids_param = sig.parameters["guardian_ids"]
        assert guardian_ids_param.default is None

    def test_intelligent_escalation_passes_guardian_ids_to_emit(self):
        """intelligent_escalation passes guardian_ids to emit_escalation_event"""
        from app.services.sequential_escalation import intelligent_escalation, EscalationContact
        
        contacts = [
            EscalationContact(phone="+91_test", name="TestGuardian", source="test", is_primary=True, priority=1)
        ]
        
        async def run_test():
            with patch("app.services.sms_service.make_voice_call_with_callback", return_value=None):
                with patch("app.services.sms_service.is_voice_available", return_value=False):
                    with patch("app.services.sms_service.is_available", return_value=False):
                        with patch("app.services.sequential_escalation.emit_escalation_event", new_callable=AsyncMock) as mock_emit:
                            await intelligent_escalation(
                                event_id="test-event",
                                contacts=contacts,
                                child_name="TestChild",
                                alert_type="test",
                                guardian_ids=["gid-1", "gid-2"],
                            )
                            
                            # Verify emit was called with guardian_ids
                            assert mock_emit.call_count >= 1
                            first_call = mock_emit.call_args_list[0]
                            # Check positional or keyword args
                            if first_call[0]:
                                assert first_call[0][0] == ["gid-1", "gid-2"]
                            else:
                                assert first_call[1].get("guardian_ids") == ["gid-1", "gid-2"]
        
        run_async(run_test())


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 5: Priority Sorting
# ═══════════════════════════════════════════════════════════════
class TestPrioritySorting:
    """Primary guardians called first, then by priority field"""

    def test_sort_contacts_by_priority_exists(self):
        """sort_contacts_by_priority function exists"""
        from app.services.sequential_escalation import sort_contacts_by_priority
        assert callable(sort_contacts_by_priority)

    def test_primary_guardians_first(self):
        """Primary guardians are sorted before non-primary"""
        from app.services.sequential_escalation import sort_contacts_by_priority, EscalationContact
        
        contacts = [
            EscalationContact(phone="+1", name="NonPrimary", source="ec", is_primary=False, priority=1),
            EscalationContact(phone="+2", name="Primary", source="rel", is_primary=True, priority=5),
        ]
        
        sorted_c = sort_contacts_by_priority(contacts)
        assert sorted_c[0].name == "Primary"
        assert sorted_c[1].name == "NonPrimary"

    def test_sort_by_priority_within_primary(self):
        """Within primary guardians, sort by priority (lower = higher)"""
        from app.services.sequential_escalation import sort_contacts_by_priority, EscalationContact
        
        contacts = [
            EscalationContact(phone="+1", name="Dad", source="rel", is_primary=True, priority=2),
            EscalationContact(phone="+2", name="Mom", source="rel", is_primary=True, priority=1),
        ]
        
        sorted_c = sort_contacts_by_priority(contacts)
        assert sorted_c[0].name == "Mom"  # priority 1
        assert sorted_c[1].name == "Dad"  # priority 2

    def test_sort_by_priority_within_non_primary(self):
        """Within non-primary, sort by priority"""
        from app.services.sequential_escalation import sort_contacts_by_priority, EscalationContact
        
        contacts = [
            EscalationContact(phone="+1", name="Neighbor", source="ec", is_primary=False, priority=10),
            EscalationContact(phone="+2", name="Uncle", source="ec", is_primary=False, priority=5),
        ]
        
        sorted_c = sort_contacts_by_priority(contacts)
        assert sorted_c[0].name == "Uncle"  # priority 5
        assert sorted_c[1].name == "Neighbor"  # priority 10

    def test_complex_sorting_scenario(self):
        """Full sorting: primary first, then by priority"""
        from app.services.sequential_escalation import sort_contacts_by_priority, EscalationContact
        
        contacts = [
            EscalationContact(phone="+1", name="Neighbor", source="ec", is_primary=False, priority=10),
            EscalationContact(phone="+2", name="Dad", source="rel", is_primary=True, priority=2),
            EscalationContact(phone="+3", name="Uncle", source="ec", is_primary=False, priority=5),
            EscalationContact(phone="+4", name="Mom", source="rel", is_primary=True, priority=1),
        ]
        
        sorted_c = sort_contacts_by_priority(contacts)
        names = [c.name for c in sorted_c]
        assert names == ["Mom", "Dad", "Uncle", "Neighbor"]


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 6: Sequential Chain Stops on Answer
# ═══════════════════════════════════════════════════════════════
class TestSequentialChainStopsOnAnswer:
    """Sequential chain stops when human answers, no SMS blast after answer"""

    def test_chain_stops_on_answered(self):
        """Chain stops immediately when call is answered"""
        from app.services.sequential_escalation import intelligent_escalation, EscalationContact
        from app.services.redis_service import set_json
        
        contacts = [
            EscalationContact(phone="+91_first", name="First", source="rel", is_primary=True, priority=1),
            EscalationContact(phone="+91_second", name="Second", source="rel", is_primary=True, priority=2),
            EscalationContact(phone="+91_third", name="Third", source="ec", is_primary=False, priority=5),
        ]
        
        call_count = [0]
        
        def mock_make_call(to, child_name, alert_type, event_id, contact_name="", callback_url=""):
            call_count[0] += 1
            sid = f"CA_stop_test_{call_count[0]}"
            # First call: simulate answered
            set_json("twilio_call", f"{sid}:resolved", "answered", ttl=60)
            return sid
        
        async def run_test():
            with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_call):
                with patch("app.services.sms_service.is_voice_available", return_value=True):
                    with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 3):
                        with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 0.5):
                            with patch("app.services.sequential_escalation.emit_escalation_event", new_callable=AsyncMock):
                                summary = await intelligent_escalation(
                                    event_id="stop-test-001",
                                    contacts=contacts,
                                    child_name="TestChild",
                                    alert_type="test",
                                )
            
            # Only 1 call should have been made (chain stopped)
            assert summary.total_calls == 1
            assert summary.resolved_by == "+91_first"
            assert not summary.sms_blast_sent
        
        run_async(run_test())

    def test_no_sms_blast_after_answer(self):
        """SMS blast is NOT sent when someone answers"""
        from app.services.sequential_escalation import intelligent_escalation, EscalationContact
        from app.services.redis_service import set_json
        
        contacts = [
            EscalationContact(phone="+91_answer", name="Answerer", source="rel", is_primary=True, priority=1),
        ]
        
        def mock_make_call(to, child_name, alert_type, event_id, contact_name="", callback_url=""):
            sid = "CA_no_sms_test"
            set_json("twilio_call", f"{sid}:resolved", "answered", ttl=60)
            return sid
        
        async def run_test():
            with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_call):
                with patch("app.services.sms_service.is_voice_available", return_value=True):
                    with patch("app.services.sms_service.send_failsafe_sms") as mock_sms:
                        with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 3):
                            with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 0.5):
                                with patch("app.services.sequential_escalation.emit_escalation_event", new_callable=AsyncMock):
                                    summary = await intelligent_escalation(
                                        event_id="no-sms-test",
                                        contacts=contacts,
                                        child_name="TestChild",
                                        alert_type="test",
                                    )
            
            assert summary.resolved_by is not None
            assert not summary.sms_blast_sent
            mock_sms.assert_not_called()
        
        run_async(run_test())


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 7: SMS Blast on Exhaustion
# ═══════════════════════════════════════════════════════════════
class TestSMSBlastOnExhaustion:
    """SMS blast fires when all contacts exhausted"""

    def test_sms_blast_when_all_exhausted(self):
        """SMS blast sent when all voice calls fail"""
        from app.services.sequential_escalation import intelligent_escalation, EscalationContact
        from app.services.redis_service import set_json
        
        contacts = [
            EscalationContact(phone="+91_fail1", name="Fail1", source="rel", is_primary=True, priority=1),
            EscalationContact(phone="+91_fail2", name="Fail2", source="rel", is_primary=True, priority=2),
        ]
        
        call_count = [0]
        
        def mock_make_call(to, child_name, alert_type, event_id, contact_name="", callback_url=""):
            call_count[0] += 1
            sid = f"CA_exhaust_test_{call_count[0]}"
            # All calls fail with no-answer
            set_json("twilio_call", f"{sid}:resolved", "no-answer", ttl=60)
            return sid
        
        sms_sent_to = []
        
        def mock_send_sms(to, child_name, alert_type, last_seen="", contact_name=""):
            sms_sent_to.append(to)
            return True
        
        async def run_test():
            with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_call):
                with patch("app.services.sms_service.is_voice_available", return_value=True):
                    with patch("app.services.sms_service.is_available", return_value=True):
                        with patch("app.services.sms_service.send_failsafe_sms", mock_send_sms):
                            with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 3):
                                with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 0.5):
                                    with patch("app.services.sequential_escalation.emit_escalation_event", new_callable=AsyncMock):
                                        summary = await intelligent_escalation(
                                            event_id="exhaust-test",
                                            contacts=contacts,
                                            child_name="TestChild",
                                            alert_type="test",
                                        )
            
            assert summary.resolved_by is None
            assert summary.sms_blast_sent
            assert summary.total_sms == 2
            assert "+91_fail1" in sms_sent_to
            assert "+91_fail2" in sms_sent_to
        
        run_async(run_test())


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 8: SSE Event Types Emitted at Each Step
# ═══════════════════════════════════════════════════════════════
class TestSSEEventTypesEmitted:
    """SSE events emitted at every step: started, calling, no_answer, voicemail, answered, sms_blast, exhausted"""

    def test_started_event_emitted(self):
        """'started' event emitted at beginning of escalation"""
        from app.services.sequential_escalation import intelligent_escalation, EscalationContact
        
        contacts = [
            EscalationContact(phone="+91_test", name="Test", source="rel", is_primary=True, priority=1),
        ]
        
        emitted_statuses = []
        
        async def capture_emit(guardian_ids, event_id, child_name, status, **kwargs):
            emitted_statuses.append(status)
        
        async def run_test():
            with patch("app.services.sms_service.is_voice_available", return_value=False):
                with patch("app.services.sms_service.is_available", return_value=False):
                    with patch("app.services.sequential_escalation.emit_escalation_event", capture_emit):
                        await intelligent_escalation(
                            event_id="started-test",
                            contacts=contacts,
                            child_name="TestChild",
                            alert_type="test",
                        )
            
            assert "started" in emitted_statuses
        
        run_async(run_test())

    def test_calling_event_emitted(self):
        """'calling' event emitted when calling a guardian"""
        from app.services.sequential_escalation import intelligent_escalation, EscalationContact
        from app.services.redis_service import set_json
        
        contacts = [
            EscalationContact(phone="+91_call", name="CallTest", source="rel", is_primary=True, priority=1),
        ]
        
        emitted_statuses = []
        
        async def capture_emit(guardian_ids, event_id, child_name, status, **kwargs):
            emitted_statuses.append(status)
        
        def mock_make_call(to, child_name, alert_type, event_id, contact_name="", callback_url=""):
            sid = "CA_calling_test"
            set_json("twilio_call", f"{sid}:resolved", "answered", ttl=60)
            return sid
        
        async def run_test():
            with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_call):
                with patch("app.services.sms_service.is_voice_available", return_value=True):
                    with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 3):
                        with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 0.5):
                            with patch("app.services.sequential_escalation.emit_escalation_event", capture_emit):
                                await intelligent_escalation(
                                    event_id="calling-test",
                                    contacts=contacts,
                                    child_name="TestChild",
                                    alert_type="test",
                                )
            
            assert "calling" in emitted_statuses
        
        run_async(run_test())

    def test_answered_event_emitted(self):
        """'answered' event emitted when call is answered"""
        from app.services.sequential_escalation import intelligent_escalation, EscalationContact
        from app.services.redis_service import set_json
        
        contacts = [
            EscalationContact(phone="+91_ans", name="AnsTest", source="rel", is_primary=True, priority=1),
        ]
        
        emitted_statuses = []
        
        async def capture_emit(guardian_ids, event_id, child_name, status, **kwargs):
            emitted_statuses.append(status)
        
        def mock_make_call(to, child_name, alert_type, event_id, contact_name="", callback_url=""):
            sid = "CA_answered_emit_test"
            set_json("twilio_call", f"{sid}:resolved", "answered", ttl=60)
            return sid
        
        async def run_test():
            with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_call):
                with patch("app.services.sms_service.is_voice_available", return_value=True):
                    with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 3):
                        with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 0.5):
                            with patch("app.services.sequential_escalation.emit_escalation_event", capture_emit):
                                await intelligent_escalation(
                                    event_id="answered-emit-test",
                                    contacts=contacts,
                                    child_name="TestChild",
                                    alert_type="test",
                                )
            
            assert "answered" in emitted_statuses
        
        run_async(run_test())

    def test_no_answer_event_emitted(self):
        """'no_answer' event emitted when call not answered"""
        from app.services.sequential_escalation import intelligent_escalation, EscalationContact
        from app.services.redis_service import set_json
        
        contacts = [
            EscalationContact(phone="+91_na", name="NATest", source="rel", is_primary=True, priority=1),
        ]
        
        emitted_statuses = []
        
        async def capture_emit(guardian_ids, event_id, child_name, status, **kwargs):
            emitted_statuses.append(status)
        
        def mock_make_call(to, child_name, alert_type, event_id, contact_name="", callback_url=""):
            sid = "CA_no_answer_emit_test"
            set_json("twilio_call", f"{sid}:resolved", "no-answer", ttl=60)
            return sid
        
        async def run_test():
            with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_call):
                with patch("app.services.sms_service.is_voice_available", return_value=True):
                    with patch("app.services.sms_service.is_available", return_value=False):
                        with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 3):
                            with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 0.5):
                                with patch("app.services.sequential_escalation.emit_escalation_event", capture_emit):
                                    await intelligent_escalation(
                                        event_id="no-answer-emit-test",
                                        contacts=contacts,
                                        child_name="TestChild",
                                        alert_type="test",
                                    )
            
            assert "no_answer" in emitted_statuses
        
        run_async(run_test())

    def test_voicemail_event_emitted(self):
        """'voicemail' event emitted when voicemail detected"""
        from app.services.sequential_escalation import intelligent_escalation, EscalationContact
        from app.services.redis_service import set_json
        
        contacts = [
            EscalationContact(phone="+91_vm", name="VMTest", source="rel", is_primary=True, priority=1),
        ]
        
        emitted_statuses = []
        
        async def capture_emit(guardian_ids, event_id, child_name, status, **kwargs):
            emitted_statuses.append(status)
        
        def mock_make_call(to, child_name, alert_type, event_id, contact_name="", callback_url=""):
            sid = "CA_voicemail_emit_test"
            set_json("twilio_call", f"{sid}:resolved", "voicemail", ttl=60)
            return sid
        
        async def run_test():
            with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_call):
                with patch("app.services.sms_service.is_voice_available", return_value=True):
                    with patch("app.services.sms_service.is_available", return_value=False):
                        with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 3):
                            with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 0.5):
                                with patch("app.services.sequential_escalation.emit_escalation_event", capture_emit):
                                    await intelligent_escalation(
                                        event_id="voicemail-emit-test",
                                        contacts=contacts,
                                        child_name="TestChild",
                                        alert_type="test",
                                    )
            
            assert "voicemail" in emitted_statuses
        
        run_async(run_test())

    def test_sms_blast_event_emitted(self):
        """'sms_blast' event emitted before SMS blast"""
        from app.services.sequential_escalation import intelligent_escalation, EscalationContact
        from app.services.redis_service import set_json
        
        contacts = [
            EscalationContact(phone="+91_sms", name="SMSTest", source="rel", is_primary=True, priority=1),
        ]
        
        emitted_statuses = []
        
        async def capture_emit(guardian_ids, event_id, child_name, status, **kwargs):
            emitted_statuses.append(status)
        
        def mock_make_call(to, child_name, alert_type, event_id, contact_name="", callback_url=""):
            sid = "CA_sms_blast_emit_test"
            set_json("twilio_call", f"{sid}:resolved", "no-answer", ttl=60)
            return sid
        
        async def run_test():
            with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_call):
                with patch("app.services.sms_service.is_voice_available", return_value=True):
                    with patch("app.services.sms_service.is_available", return_value=True):
                        with patch("app.services.sms_service.send_failsafe_sms", return_value=True):
                            with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 3):
                                with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 0.5):
                                    with patch("app.services.sequential_escalation.emit_escalation_event", capture_emit):
                                        await intelligent_escalation(
                                            event_id="sms-blast-emit-test",
                                            contacts=contacts,
                                            child_name="TestChild",
                                            alert_type="test",
                                        )
            
            assert "sms_blast" in emitted_statuses
        
        run_async(run_test())

    def test_exhausted_event_emitted(self):
        """'exhausted' event emitted after SMS blast"""
        from app.services.sequential_escalation import intelligent_escalation, EscalationContact
        from app.services.redis_service import set_json
        
        contacts = [
            EscalationContact(phone="+91_exh", name="ExhTest", source="rel", is_primary=True, priority=1),
        ]
        
        emitted_statuses = []
        
        async def capture_emit(guardian_ids, event_id, child_name, status, **kwargs):
            emitted_statuses.append(status)
        
        def mock_make_call(to, child_name, alert_type, event_id, contact_name="", callback_url=""):
            sid = "CA_exhausted_emit_test"
            set_json("twilio_call", f"{sid}:resolved", "no-answer", ttl=60)
            return sid
        
        async def run_test():
            with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_call):
                with patch("app.services.sms_service.is_voice_available", return_value=True):
                    with patch("app.services.sms_service.is_available", return_value=True):
                        with patch("app.services.sms_service.send_failsafe_sms", return_value=True):
                            with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 3):
                                with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 0.5):
                                    with patch("app.services.sequential_escalation.emit_escalation_event", capture_emit):
                                        await intelligent_escalation(
                                            event_id="exhausted-emit-test",
                                            contacts=contacts,
                                            child_name="TestChild",
                                            alert_type="test",
                                        )
            
            assert "exhausted" in emitted_statuses
        
        run_async(run_test())


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 9: auto_escalation_engine guardian_ids Collection
# ═══════════════════════════════════════════════════════════════
class TestAutoEscalationEngineGuardianIds:
    """auto_escalation_engine.py collects guardian_ids and passes to intelligent_escalation"""

    def test_trigger_guardian_failsafe_collects_guardian_ids(self):
        """_trigger_guardian_failsafe collects notified_guardian_ids"""
        import inspect
        from app.services.auto_escalation_engine import _trigger_guardian_failsafe
        
        source = inspect.getsource(_trigger_guardian_failsafe)
        
        # Verify notified_guardian_ids is collected
        assert "notified_guardian_ids" in source
        assert "notified_guardian_ids.append" in source or "notified_guardian_ids:" in source

    def test_trigger_guardian_failsafe_passes_guardian_ids_to_intelligent_escalation(self):
        """_trigger_guardian_failsafe passes guardian_ids to intelligent_escalation"""
        import inspect
        from app.services.auto_escalation_engine import _trigger_guardian_failsafe
        
        source = inspect.getsource(_trigger_guardian_failsafe)
        
        # Verify intelligent_escalation is called with guardian_ids
        assert "intelligent_escalation" in source
        assert "guardian_ids=" in source or "guardian_ids=notified_guardian_ids" in source

    def test_auto_escalation_imports_intelligent_escalation(self):
        """auto_escalation_engine imports intelligent_escalation"""
        import inspect
        from app.services import auto_escalation_engine
        
        source = inspect.getsource(auto_escalation_engine)
        assert "from app.services.sequential_escalation import" in source
        assert "intelligent_escalation" in source


# ═══════════════════════════════════════════════════════════════
# TEST GROUP 10: EscalationLiveFeed Component Structure
# ═══════════════════════════════════════════════════════════════
class TestEscalationLiveFeedComponent:
    """Web CommandCenter EscalationLiveFeed component renders with correct table structure"""

    def test_escalation_live_feed_file_exists(self):
        """EscalationLiveFeed.jsx file exists"""
        import os
        path = "/app/frontend/src/components/command-center/EscalationLiveFeed.jsx"
        assert os.path.exists(path), f"File not found: {path}"

    def test_escalation_live_feed_has_table_structure(self):
        """EscalationLiveFeed has table with correct columns"""
        with open("/app/frontend/src/components/command-center/EscalationLiveFeed.jsx", "r") as f:
            content = f.read()
        
        # Check for table structure
        assert "<table" in content
        assert "<thead>" in content
        assert "<tbody>" in content
        
        # Check for required columns
        assert "Child" in content
        assert "Guardian" in content
        assert "Status" in content
        assert "Step" in content or "sequence" in content.lower()
        assert "Time" in content or "timestamp" in content.lower()

    def test_escalation_live_feed_has_status_config(self):
        """EscalationLiveFeed has STATUS_CONFIG for all event types"""
        with open("/app/frontend/src/components/command-center/EscalationLiveFeed.jsx", "r") as f:
            content = f.read()
        
        # Check for all status types
        assert "started" in content
        assert "calling" in content
        assert "no_answer" in content
        assert "voicemail" in content
        assert "answered" in content
        assert "sms_blast" in content
        assert "exhausted" in content

    def test_escalation_live_feed_has_data_testid(self):
        """EscalationLiveFeed has data-testid attributes"""
        with open("/app/frontend/src/components/command-center/EscalationLiveFeed.jsx", "r") as f:
            content = f.read()
        
        assert 'data-testid="escalation-live-feed"' in content

    def test_escalation_live_feed_has_pulse_animation(self):
        """EscalationLiveFeed has pulse animation for active calls"""
        with open("/app/frontend/src/components/command-center/EscalationLiveFeed.jsx", "r") as f:
            content = f.read()
        
        assert "animate-pulse" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
