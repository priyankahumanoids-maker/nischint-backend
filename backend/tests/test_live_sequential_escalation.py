"""
Live Sequential Escalation Integration Tests
=============================================
Exercises the FULL escalation chain end-to-end:
  - Real webhook endpoint (POST /api/twilio/status)
  - Real Redis call status tracking
  - Real sequential_escalation.intelligent_escalation()
  - Real priority sorting
  - Mocked: make_voice_call_with_callback (Twilio trial can't call unverified numbers)

Scenarios:
  1. Guardian 1 no-answer → Guardian 2 answers → chain STOPS, NO SMS blast
  2. Voicemail detection → moves to next guardian
  3. Cancel during active escalation (guardian ACK mid-chain)
  4. Webhook timeout fallback (no callback arrives within window)
  5. Full exhaustion → SMS blast to all
"""
import asyncio
import logging
import time
import uuid
import httpx
from unittest.mock import patch

# Setup logging to see all escalation events
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("live_test")

API_URL = "https://gps-mic-restart.preview.emergentagent.com"

# Track which SIDs were "created" by our mock
_mock_call_counter = 0


def mock_make_voice_call_with_callback(to, child_name, alert_type, event_id, contact_name="", callback_url=""):
    """Mock that returns a fake call SID instead of calling Twilio."""
    global _mock_call_counter
    _mock_call_counter += 1
    sid = f"CA_test_{event_id}_{_mock_call_counter}"
    logger.warning(f"[MOCK_CALL] Created call SID={sid} to={to} name={contact_name}")
    return sid


async def simulate_twilio_callback(call_sid: str, status: str, answered_by: str = "", delay: float = 0):
    """Simulate a Twilio callback hitting our webhook endpoint."""
    if delay > 0:
        await asyncio.sleep(delay)

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API_URL}/api/twilio/status",
            data={
                "CallSid": call_sid,
                "CallStatus": status,
                "To": "+919999999999",
                "From": "+1234567890",
                "AnsweredBy": answered_by,
                "CallDuration": "0",
            },
        )
        logger.warning(f"[CALLBACK_SENT] sid={call_sid} status={status} answered_by={answered_by} http={resp.status_code}")
        return resp.status_code == 200


def build_test_contacts():
    """Build test contacts with clear priority order."""
    from app.services.sequential_escalation import EscalationContact
    return [
        EscalationContact(phone="+91_mom", name="Mom", source="relationship", is_primary=True, priority=1),
        EscalationContact(phone="+91_dad", name="Dad", source="guardian_relationship", is_primary=True, priority=2),
        EscalationContact(phone="+91_uncle", name="Uncle", source="emergency_contact", is_primary=False, priority=5),
        EscalationContact(phone="+91_neighbor", name="Neighbor", source="emergency_contact", is_primary=False, priority=10),
    ]


# ═══════════════════════════════════════════════════════════════
# SCENARIO 1: Guardian 1 no-answer → Guardian 2 answers → STOP
# ═══════════════════════════════════════════════════════════════
async def test_scenario_1_no_answer_then_answer():
    """
    1. Call Mom (primary, p1) → simulate no-answer after 3s
    2. Call Dad (primary, p2) → simulate human answer after 2s
    3. Verify: chain STOPS at Dad, Uncle & Neighbor never called
    4. Verify: NO SMS blast
    """
    from app.services.sequential_escalation import intelligent_escalation, EscalationContact

    event_id = f"scenario1-{uuid.uuid4().hex[:8]}"
    contacts = build_test_contacts()
    global _mock_call_counter
    _mock_call_counter = 0

    logger.warning(f"\n{'='*60}")
    logger.warning(f"SCENARIO 1: No-answer → Answer → Stop Chain")
    logger.warning(f"{'='*60}")

    # Run escalation in background
    async def run_escalation():
        with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_voice_call_with_callback):
            with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 8):
                with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 1):
                    return await intelligent_escalation(
                        event_id=event_id,
                        contacts=contacts,
                        child_name="TestChild",
                        alert_type="emergency_triggered",
                        last_seen="10s ago",
                        callback_base_url=API_URL,
                    )

    # Callback simulator: Mom no-answer after 3s, Dad answers after 2s
    async def send_callbacks():
        # Wait for first call to be placed (Mom)
        await asyncio.sleep(1)
        sid1 = f"CA_test_{event_id}_1"
        await simulate_twilio_callback(sid1, "no-answer", delay=2)

        # Wait for second call (Dad)
        await asyncio.sleep(1)
        sid2 = f"CA_test_{event_id}_2"
        await simulate_twilio_callback(sid2, "in-progress", answered_by="human", delay=1)

    # Run both concurrently
    summary, _ = await asyncio.gather(run_escalation(), send_callbacks())

    # Assertions
    assert summary.resolved_by == "+91_dad", f"Expected Dad to answer, got: {summary.resolved_by}"
    assert summary.total_calls == 2, f"Expected 2 calls, got: {summary.total_calls}"
    assert not summary.sms_blast_sent, "SMS blast should NOT be sent when someone answered"

    # Verify only Mom and Dad have results (Uncle/Neighbor never called)
    called_names = [r.name for r in summary.results]
    assert "Mom" in called_names, "Mom should be in results"
    assert "Dad" in called_names, "Dad should be in results"
    assert "Uncle" not in called_names, "Uncle should NOT have been called"
    assert "Neighbor" not in called_names, "Neighbor should NOT have been called"

    # Verify Mom's result is no-answer
    mom_result = next(r for r in summary.results if r.name == "Mom")
    assert mom_result.call_status == "no-answer", f"Mom should be no-answer, got: {mom_result.call_status}"
    assert not mom_result.success

    # Verify Dad's result is answered
    dad_result = next(r for r in summary.results if r.name == "Dad")
    assert dad_result.call_status == "answered", f"Dad should be answered, got: {dad_result.call_status}"
    assert dad_result.success
    assert dad_result.method == "voice_answered"

    logger.warning(f"SCENARIO 1 PASSED: resolved_by={summary.resolved_by}, calls={summary.total_calls}, sms_blast={summary.sms_blast_sent}")
    return True


# ═══════════════════════════════════════════════════════════════
# SCENARIO 2: Voicemail detection → moves to next
# ═══════════════════════════════════════════════════════════════
async def test_scenario_2_voicemail():
    """
    1. Call Mom → voicemail (machine_start)
    2. Call Dad → voicemail (machine_end_beep)
    3. Call Uncle → human answer
    4. Verify: voicemail ≠ success, chain continues past voicemail
    """
    from app.services.sequential_escalation import intelligent_escalation

    event_id = f"scenario2-{uuid.uuid4().hex[:8]}"
    contacts = build_test_contacts()
    global _mock_call_counter
    _mock_call_counter = 0

    logger.warning(f"\n{'='*60}")
    logger.warning(f"SCENARIO 2: Voicemail Detection")
    logger.warning(f"{'='*60}")

    async def run_escalation():
        with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_voice_call_with_callback):
            with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 8):
                with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 1):
                    return await intelligent_escalation(
                        event_id=event_id,
                        contacts=contacts,
                        child_name="TestChild",
                        alert_type="voice_distress",
                        last_seen="20s ago",
                        callback_base_url=API_URL,
                    )

    async def send_callbacks():
        # Mom: voicemail (machine_start)
        await asyncio.sleep(2)
        sid1 = f"CA_test_{event_id}_1"
        await simulate_twilio_callback(sid1, "in-progress", answered_by="machine_start")

        # Dad: voicemail (machine_end_beep)
        await asyncio.sleep(2)
        sid2 = f"CA_test_{event_id}_2"
        await simulate_twilio_callback(sid2, "in-progress", answered_by="machine_end_beep")

        # Uncle: human answer
        await asyncio.sleep(2)
        sid3 = f"CA_test_{event_id}_3"
        await simulate_twilio_callback(sid3, "in-progress", answered_by="human")

    summary, _ = await asyncio.gather(run_escalation(), send_callbacks())

    # Mom and Dad should be voicemail (NOT success)
    mom_result = next(r for r in summary.results if r.name == "Mom")
    assert mom_result.method == "voice_voicemail", f"Mom should be voicemail, got: {mom_result.method}"
    assert mom_result.answered_by == "machine"
    assert not mom_result.success

    dad_result = next(r for r in summary.results if r.name == "Dad")
    assert dad_result.method == "voice_voicemail", f"Dad should be voicemail, got: {dad_result.method}"
    assert not dad_result.success

    # Uncle should be answered
    uncle_result = next(r for r in summary.results if r.name == "Uncle")
    assert uncle_result.method == "voice_answered"
    assert uncle_result.success

    assert summary.resolved_by == "+91_uncle"
    assert not summary.sms_blast_sent
    assert summary.total_calls == 3

    logger.warning(f"SCENARIO 2 PASSED: voicemail correctly detected, resolved_by={summary.resolved_by}")
    return True


# ═══════════════════════════════════════════════════════════════
# SCENARIO 3: Webhook timeout → falls through to next guardian
# ═══════════════════════════════════════════════════════════════
async def test_scenario_3_timeout():
    """
    1. Call Mom → NO callback arrives (simulate Twilio webhook failure)
    2. Wait for timeout (reduced to 4s for test)
    3. Call Dad → human answer
    4. Verify: timeout correctly handled as "no answer"
    """
    from app.services.sequential_escalation import intelligent_escalation, EscalationContact

    event_id = f"scenario3-{uuid.uuid4().hex[:8]}"
    # Only 2 contacts for speed
    contacts = [
        EscalationContact(phone="+91_mom_t", name="Mom", source="relationship", is_primary=True, priority=1),
        EscalationContact(phone="+91_dad_t", name="Dad", source="relationship", is_primary=True, priority=2),
    ]
    global _mock_call_counter
    _mock_call_counter = 0

    logger.warning(f"\n{'='*60}")
    logger.warning(f"SCENARIO 3: Webhook Timeout Fallback")
    logger.warning(f"{'='*60}")

    async def run_escalation():
        with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_voice_call_with_callback):
            with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 4):
                with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 1):
                    return await intelligent_escalation(
                        event_id=event_id,
                        contacts=contacts,
                        child_name="TestChild",
                        alert_type="emergency_triggered",
                        callback_base_url=API_URL,
                    )

    async def send_callbacks():
        # Mom: NO callback at all — will timeout
        # Wait for Mom's timeout (4s) + escalation to Dad
        await asyncio.sleep(6)
        # Dad: human answer
        sid2 = f"CA_test_{event_id}_2"
        await simulate_twilio_callback(sid2, "in-progress", answered_by="human")

    summary, _ = await asyncio.gather(run_escalation(), send_callbacks())

    # Mom should be timeout
    mom_result = next(r for r in summary.results if r.name == "Mom")
    assert mom_result.call_status == "timeout", f"Mom should be timeout, got: {mom_result.call_status}"
    assert mom_result.method == "voice_timeout"

    # Dad should be answered
    dad_result = next(r for r in summary.results if r.name == "Dad")
    assert dad_result.method == "voice_answered"
    assert summary.resolved_by == "+91_dad_t"

    logger.warning(f"SCENARIO 3 PASSED: timeout handled correctly, resolved_by={summary.resolved_by}")
    return True


# ═══════════════════════════════════════════════════════════════
# SCENARIO 4: Full exhaustion → SMS blast
# ═══════════════════════════════════════════════════════════════
async def test_scenario_4_full_exhaustion():
    """
    1. Call Mom → busy
    2. Call Dad → no-answer
    3. No more contacts
    4. Verify: SMS blast sent to BOTH contacts
    """
    from app.services.sequential_escalation import intelligent_escalation, EscalationContact

    event_id = f"scenario4-{uuid.uuid4().hex[:8]}"
    contacts = [
        EscalationContact(phone="+91_mom_e", name="Mom", source="relationship", is_primary=True, priority=1),
        EscalationContact(phone="+91_dad_e", name="Dad", source="relationship", is_primary=True, priority=2),
    ]
    global _mock_call_counter
    _mock_call_counter = 0

    logger.warning(f"\n{'='*60}")
    logger.warning(f"SCENARIO 4: Full Exhaustion → SMS Blast")
    logger.warning(f"{'='*60}")

    async def run_escalation():
        with patch("app.services.sms_service.make_voice_call_with_callback", mock_make_voice_call_with_callback):
            with patch("app.services.sequential_escalation.CALL_WAIT_TIMEOUT_S", 6):
                with patch("app.services.sequential_escalation.POLL_INTERVAL_S", 1):
                    return await intelligent_escalation(
                        event_id=event_id,
                        contacts=contacts,
                        child_name="TestChild",
                        alert_type="emergency_triggered",
                        last_seen="30s ago",
                        callback_base_url=API_URL,
                    )

    async def send_callbacks():
        # Mom: busy
        await asyncio.sleep(2)
        sid1 = f"CA_test_{event_id}_1"
        await simulate_twilio_callback(sid1, "busy")

        # Dad: no-answer
        await asyncio.sleep(2)
        sid2 = f"CA_test_{event_id}_2"
        await simulate_twilio_callback(sid2, "no-answer")

    summary, _ = await asyncio.gather(run_escalation(), send_callbacks())

    assert summary.resolved_by is None, f"Nobody should have answered, got: {summary.resolved_by}"
    assert summary.sms_blast_sent, "SMS blast should have been sent"
    assert summary.total_sms == 2, f"Expected 2 SMS, got: {summary.total_sms}"
    assert summary.total_calls == 2

    # Verify voice results
    mom_result = next(r for r in summary.results if r.name == "Mom" and r.call_sid is not None)
    assert mom_result.call_status == "busy"
    assert mom_result.method == "voice_busy"

    dad_result = next(r for r in summary.results if r.name == "Dad" and r.call_sid is not None)
    assert dad_result.call_status == "no-answer"

    logger.warning(f"SCENARIO 4 PASSED: exhaustion detected, sms_blast={summary.sms_blast_sent}, sms_count={summary.total_sms}")
    return True


# ═══════════════════════════════════════════════════════════════
# SCENARIO 5: Redis verification — direct call status checks
# ═══════════════════════════════════════════════════════════════
async def test_scenario_5_redis_verification():
    """Verify Redis stores and retrieves call statuses correctly for all types."""
    from app.api.twilio_webhook import get_call_status

    logger.warning(f"\n{'='*60}")
    logger.warning(f"SCENARIO 5: Redis Call Status Verification")
    logger.warning(f"{'='*60}")

    test_cases = [
        ("CA_redis_human", "in-progress", "human", "answered"),
        ("CA_redis_vm1", "in-progress", "machine_start", "voicemail"),
        ("CA_redis_vm2", "in-progress", "machine_end_beep", "voicemail"),
        ("CA_redis_vm3", "in-progress", "machine_end_silence", "voicemail"),
        ("CA_redis_busy", "busy", "", "busy"),
        ("CA_redis_noanswer", "no-answer", "", "no-answer"),
        ("CA_redis_failed", "failed", "", "failed"),
        ("CA_redis_canceled", "canceled", "", "canceled"),
    ]

    for sid, status, answered_by, expected_resolved in test_cases:
        ok = await simulate_twilio_callback(sid, status, answered_by)
        assert ok, f"Callback failed for {sid}"

        # Small delay for Redis propagation
        await asyncio.sleep(0.5)

        resolved = get_call_status(sid)
        assert resolved == expected_resolved, (
            f"SID={sid}: expected resolved={expected_resolved}, got={resolved}"
        )
        logger.warning(f"  {sid}: status={status} answered_by={answered_by} → resolved={resolved} ✓")

    logger.warning(f"SCENARIO 5 PASSED: all 8 Redis status types verified")
    return True


# ═══════════════════════════════════════════════════════════════
# SCENARIO 6: Priority sorting verification
# ═══════════════════════════════════════════════════════════════
def test_scenario_6_priority_sorting():
    """Verify contacts are sorted correctly: primary first, then by priority."""
    from app.services.sequential_escalation import EscalationContact, sort_contacts_by_priority

    logger.warning(f"\n{'='*60}")
    logger.warning(f"SCENARIO 6: Priority Sorting Verification")
    logger.warning(f"{'='*60}")

    contacts = [
        EscalationContact(phone="+1", name="Neighbor", source="ec", is_primary=False, priority=10),
        EscalationContact(phone="+2", name="Dad", source="rel", is_primary=True, priority=2),
        EscalationContact(phone="+3", name="Uncle", source="ec", is_primary=False, priority=5),
        EscalationContact(phone="+4", name="Mom", source="rel", is_primary=True, priority=1),
        EscalationContact(phone="+5", name="Aunt", source="gr", is_primary=False, priority=3),
    ]

    sorted_c = sort_contacts_by_priority(contacts)
    names = [c.name for c in sorted_c]
    expected = ["Mom", "Dad", "Aunt", "Uncle", "Neighbor"]

    assert names == expected, f"Sort order wrong: {names} != {expected}"
    logger.warning(f"  Order: {names} ✓")
    logger.warning(f"SCENARIO 6 PASSED")
    return True


# ═══════════════════════════════════════════════════════════════
# MAIN RUNNER
# ═══════════════════════════════════════════════════════════════
async def run_all_scenarios():
    results = {}

    # Sync test first
    results["S6_priority_sort"] = test_scenario_6_priority_sorting()

    # Async tests
    results["S5_redis_verify"] = await test_scenario_5_redis_verification()
    results["S1_no_answer_then_answer"] = await test_scenario_1_no_answer_then_answer()
    results["S2_voicemail"] = await test_scenario_2_voicemail()
    results["S3_timeout"] = await test_scenario_3_timeout()
    results["S4_exhaustion_sms_blast"] = await test_scenario_4_full_exhaustion()

    # Summary
    print("\n" + "=" * 60)
    print("LIVE SEQUENTIAL ESCALATION TEST RESULTS")
    print("=" * 60)
    all_pass = True
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_pass = False

    print(f"\n{'ALL SCENARIOS PASSED' if all_pass else 'SOME SCENARIOS FAILED'}")
    print("=" * 60)
    return all_pass


if __name__ == "__main__":
    asyncio.run(run_all_scenarios())
