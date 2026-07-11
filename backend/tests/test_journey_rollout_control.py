"""
NISCHINT Journey Engine — Rollout Control System Tests (v5.2)

Tests for:
- Rollout config API (GET/POST /api/journey/rollout/config)
- Emergency stop (kill switch) API
- Session allowlist CRUD + bulk add
- Gate check API (4-layer gate decision)
- Metrics API (totals + per-session)
- Mongo persistence (journey_rollout_config, journey_rollout_allowlist, journey_rollout_metrics)
- Delivery gate integration with SOS flow
- Metrics recording end-to-end
- Delivery confidence calculation
"""
import os
import time
import pytest
import requests
from datetime import datetime

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://gps-mic-restart.preview.emergentagent.com"

# Test session IDs (prefixed for cleanup)
TEST_SESSION_1 = "TEST_rollout_session_001"
TEST_SESSION_2 = "TEST_rollout_session_002"
TEST_SESSION_3 = "TEST_rollout_session_003"
TEST_BULK_SESSIONS = ["TEST_bulk_001", "TEST_bulk_002", "TEST_bulk_003"]


class TestRolloutConfigAPI:
    """Tests for GET/POST /api/journey/rollout/config"""

    def test_get_config_returns_expected_structure(self):
        """GET /api/journey/rollout/config returns config, env, stages, allowlist_counts"""
        r = requests.get(f"{BASE_URL}/api/journey/rollout/config")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        
        # Verify top-level keys
        assert "config" in data, "Missing 'config' key"
        assert "env" in data, "Missing 'env' key"
        assert "stages" in data, "Missing 'stages' key"
        assert "allowlist_counts" in data, "Missing 'allowlist_counts' key"
        
        # Verify config structure
        cfg = data["config"]
        assert "emergency_stop" in cfg, "Missing 'emergency_stop' in config"
        assert "current_stage" in cfg, "Missing 'current_stage' in config"
        
        # Verify env structure
        env = data["env"]
        assert "live_delivery_flag" in env, "Missing 'live_delivery_flag' in env"
        assert "max_sos_per_hour" in env, "Missing 'max_sos_per_hour' in env"
        
        # Verify stages structure (3 stages)
        stages = data["stages"]
        assert "stage1_internal" in stages, "Missing stage1_internal"
        assert "stage2_controlled" in stages, "Missing stage2_controlled"
        assert "stage3_soft_launch" in stages, "Missing stage3_soft_launch"
        assert stages["stage1_internal"]["target"] == 5
        assert stages["stage2_controlled"]["target"] == 50
        assert stages["stage3_soft_launch"]["target"] == 500
        
        # Verify allowlist_counts structure
        counts = data["allowlist_counts"]
        assert "total_sessions" in counts
        assert "enabled_total" in counts
        assert "by_stage" in counts
        
        print(f"✓ Config API returns expected structure: emergency_stop={cfg['emergency_stop']}, stage={cfg['current_stage']}")

    def test_update_config_stage(self):
        """POST /api/journey/rollout/config with current_stage updates and returns new config"""
        # First get current stage
        r1 = requests.get(f"{BASE_URL}/api/journey/rollout/config")
        original_stage = r1.json()["config"]["current_stage"]
        
        # Update to stage2_controlled
        r2 = requests.post(
            f"{BASE_URL}/api/journey/rollout/config",
            json={"current_stage": "stage2_controlled", "actor": "test_agent"}
        )
        assert r2.status_code == 200, f"Expected 200, got {r2.status_code}: {r2.text}"
        data = r2.json()
        assert data["status"] == "ok"
        assert data["config"]["current_stage"] == "stage2_controlled"
        
        # Verify via GET
        r3 = requests.get(f"{BASE_URL}/api/journey/rollout/config")
        assert r3.json()["config"]["current_stage"] == "stage2_controlled"
        
        # Restore original stage
        requests.post(
            f"{BASE_URL}/api/journey/rollout/config",
            json={"current_stage": original_stage, "actor": "test_cleanup"}
        )
        
        print(f"✓ Config stage update works: changed to stage2_controlled, restored to {original_stage}")

    def test_update_config_invalid_stage_returns_400(self):
        """POST /api/journey/rollout/config with invalid stage returns 400"""
        r = requests.post(
            f"{BASE_URL}/api/journey/rollout/config",
            json={"current_stage": "invalid_stage_xyz"}
        )
        assert r.status_code == 400, f"Expected 400 for invalid stage, got {r.status_code}"
        print("✓ Invalid stage returns 400")


class TestEmergencyStopAPI:
    """Tests for emergency stop (kill switch) API"""

    def test_engage_emergency_stop(self):
        """POST /api/journey/rollout/emergency-stop engages kill switch"""
        r = requests.post(f"{BASE_URL}/api/journey/rollout/emergency-stop?actor=test_agent")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data["status"] == "engaged"
        assert data["config"]["emergency_stop"] == True
        
        # Verify via GET
        r2 = requests.get(f"{BASE_URL}/api/journey/rollout/config")
        assert r2.json()["config"]["emergency_stop"] == True
        
        print("✓ Emergency stop engaged successfully")

    def test_release_emergency_stop(self):
        """POST /api/journey/rollout/emergency-release disengages kill switch"""
        # First engage
        requests.post(f"{BASE_URL}/api/journey/rollout/emergency-stop?actor=test_agent")
        
        # Then release
        r = requests.post(f"{BASE_URL}/api/journey/rollout/emergency-release?actor=test_agent")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data["status"] == "released"
        assert data["config"]["emergency_stop"] == False
        
        # Verify via GET
        r2 = requests.get(f"{BASE_URL}/api/journey/rollout/config")
        assert r2.json()["config"]["emergency_stop"] == False
        
        print("✓ Emergency stop released successfully")


class TestAllowlistAPI:
    """Tests for session allowlist CRUD"""

    def test_add_session_to_allowlist(self):
        """POST /api/journey/rollout/allowlist adds a session"""
        r = requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={
                "session_id": TEST_SESSION_1,
                "enabled": True,
                "stage": "stage1_internal",
                "added_by": "test_agent",
                "notes": "Test session for rollout testing"
            }
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data["status"] == "ok"
        assert data["session"]["session_id"] == TEST_SESSION_1
        assert data["session"]["enabled"] == True
        assert data["session"]["stage"] == "stage1_internal"
        
        print(f"✓ Session {TEST_SESSION_1} added to allowlist")

    def test_get_allowlist(self):
        """GET /api/journey/rollout/allowlist returns list"""
        # First add a session
        requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={"session_id": TEST_SESSION_1, "enabled": True, "stage": "stage1_internal"}
        )
        
        r = requests.get(f"{BASE_URL}/api/journey/rollout/allowlist")
        assert r.status_code == 200
        data = r.json()
        assert "allowlist" in data
        assert "count" in data
        assert isinstance(data["allowlist"], list)
        
        # Verify our test session is in the list
        session_ids = [s["session_id"] for s in data["allowlist"]]
        assert TEST_SESSION_1 in session_ids, f"Test session not found in allowlist"
        
        print(f"✓ Allowlist returned {data['count']} sessions")

    def test_get_allowlist_filter_by_stage(self):
        """GET /api/journey/rollout/allowlist?stage=stage1_internal filters by stage"""
        # Add sessions to different stages
        requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={"session_id": TEST_SESSION_1, "enabled": True, "stage": "stage1_internal"}
        )
        requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={"session_id": TEST_SESSION_2, "enabled": True, "stage": "stage2_controlled"}
        )
        
        r = requests.get(f"{BASE_URL}/api/journey/rollout/allowlist?stage=stage1_internal")
        assert r.status_code == 200
        data = r.json()
        
        # All returned sessions should be stage1_internal
        for s in data["allowlist"]:
            assert s["stage"] == "stage1_internal", f"Expected stage1_internal, got {s['stage']}"
        
        print(f"✓ Stage filter works: {data['count']} sessions in stage1_internal")

    def test_get_allowlist_filter_enabled_only(self):
        """GET /api/journey/rollout/allowlist?enabled_only=true filters enabled sessions"""
        # Add enabled and disabled sessions
        requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={"session_id": TEST_SESSION_1, "enabled": True, "stage": "stage1_internal"}
        )
        requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={"session_id": TEST_SESSION_3, "enabled": False, "stage": "stage1_internal"}
        )
        
        r = requests.get(f"{BASE_URL}/api/journey/rollout/allowlist?enabled_only=true")
        assert r.status_code == 200
        data = r.json()
        
        # All returned sessions should be enabled
        for s in data["allowlist"]:
            assert s["enabled"] == True, f"Expected enabled=True, got {s['enabled']}"
        
        print(f"✓ Enabled filter works: {data['count']} enabled sessions")

    def test_delete_session_from_allowlist(self):
        """DELETE /api/journey/rollout/allowlist/{session_id} removes session"""
        # First add
        requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={"session_id": TEST_SESSION_1, "enabled": True, "stage": "stage1_internal"}
        )
        
        # Then delete
        r = requests.delete(f"{BASE_URL}/api/journey/rollout/allowlist/{TEST_SESSION_1}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data["status"] == "ok"
        assert data["removed"] == TEST_SESSION_1
        
        # Verify removed
        r2 = requests.get(f"{BASE_URL}/api/journey/rollout/allowlist")
        session_ids = [s["session_id"] for s in r2.json()["allowlist"]]
        assert TEST_SESSION_1 not in session_ids, "Session should be removed"
        
        print(f"✓ Session {TEST_SESSION_1} removed from allowlist")

    def test_delete_nonexistent_session_returns_404(self):
        """DELETE /api/journey/rollout/allowlist/{session_id} returns 404 for unknown session"""
        r = requests.delete(f"{BASE_URL}/api/journey/rollout/allowlist/nonexistent_session_xyz")
        assert r.status_code == 404, f"Expected 404, got {r.status_code}"
        print("✓ Delete nonexistent session returns 404")

    def test_bulk_add_sessions(self):
        """POST /api/journey/rollout/allowlist/bulk adds multiple sessions"""
        r = requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist/bulk",
            json={
                "session_ids": TEST_BULK_SESSIONS,
                "enabled": True,
                "stage": "stage1_internal",
                "added_by": "test_agent",
                "notes": "Bulk test sessions"
            }
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data["status"] == "ok"
        assert data["added"] == len(TEST_BULK_SESSIONS)
        
        # Verify all sessions added
        r2 = requests.get(f"{BASE_URL}/api/journey/rollout/allowlist")
        session_ids = [s["session_id"] for s in r2.json()["allowlist"]]
        for sid in TEST_BULK_SESSIONS:
            assert sid in session_ids, f"Bulk session {sid} not found"
        
        print(f"✓ Bulk add: {data['added']} sessions added")


class TestGateCheckAPI:
    """Tests for gate check API (4-layer gate decision)"""

    def test_gate_check_unknown_session_not_allowed(self):
        """GET /api/journey/rollout/gate-check/{session_id} returns allowed=false for unknown session"""
        r = requests.get(f"{BASE_URL}/api/journey/rollout/gate-check/unknown_session_xyz")
        assert r.status_code == 200
        data = r.json()
        
        assert data["gate_decision"]["allowed"] == False
        assert data["gate_decision"]["reason"] == "session_not_allowlisted"
        
        print("✓ Unknown session gate check: allowed=false, reason=session_not_allowlisted")

    def test_gate_check_allowlisted_session_ok(self):
        """GET /api/journey/rollout/gate-check/{session_id} returns reason=ok for allowlisted session"""
        # Ensure emergency stop is released
        requests.post(f"{BASE_URL}/api/journey/rollout/emergency-release?actor=test_agent")
        
        # Add session to allowlist
        requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={"session_id": TEST_SESSION_1, "enabled": True, "stage": "stage1_internal"}
        )
        
        r = requests.get(f"{BASE_URL}/api/journey/rollout/gate-check/{TEST_SESSION_1}")
        assert r.status_code == 200
        data = r.json()
        
        assert data["gate_decision"]["reason"] == "ok"
        # Note: allowed may still be false if live_flag is off, but reason should be "ok" from allowlist perspective
        
        print(f"✓ Allowlisted session gate check: reason=ok, would_deliver_real={data['would_deliver_real']}")

    def test_gate_check_emergency_stop_blocks_all(self):
        """GET /api/journey/rollout/gate-check/{session_id} returns reason=emergency_stop when kill switch engaged"""
        # Add session to allowlist
        requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={"session_id": TEST_SESSION_1, "enabled": True, "stage": "stage1_internal"}
        )
        
        # Engage emergency stop
        requests.post(f"{BASE_URL}/api/journey/rollout/emergency-stop?actor=test_agent")
        
        # Check gate - should be blocked even for allowlisted session
        r = requests.get(f"{BASE_URL}/api/journey/rollout/gate-check/{TEST_SESSION_1}")
        assert r.status_code == 200
        data = r.json()
        
        assert data["gate_decision"]["allowed"] == False
        assert data["gate_decision"]["reason"] == "emergency_stop"
        assert data["would_deliver_real"] == False
        
        # Release emergency stop for other tests
        requests.post(f"{BASE_URL}/api/journey/rollout/emergency-release?actor=test_agent")
        
        print("✓ Emergency stop blocks ALL sessions (even allowlisted)")


class TestMetricsAPI:
    """Tests for metrics API"""

    def test_get_metrics_totals(self):
        """GET /api/journey/rollout/metrics returns totals and top_sessions"""
        r = requests.get(f"{BASE_URL}/api/journey/rollout/metrics")
        assert r.status_code == 200
        data = r.json()
        
        assert "totals" in data
        assert "top_sessions" in data
        assert "sessions_tracked" in data
        
        totals = data["totals"]
        assert "sos" in totals
        assert "sms_real" in totals
        assert "sms_sim" in totals
        assert "push_real" in totals
        assert "push_sim" in totals
        assert "ack_count" in totals
        assert "avg_ack_seconds" in totals
        assert "avg_delivery_confidence" in totals
        
        print(f"✓ Metrics API: {data['sessions_tracked']} sessions tracked, {totals['sos']} total SOS")

    def test_get_session_metrics(self):
        """GET /api/journey/rollout/metrics/{session_id} returns per-session metrics"""
        r = requests.get(f"{BASE_URL}/api/journey/rollout/metrics/{TEST_SESSION_1}")
        assert r.status_code == 200
        data = r.json()
        
        assert "session_id" in data
        assert "sos_count" in data
        assert "sms_real" in data
        assert "sms_sim" in data
        assert "push_real" in data
        assert "push_sim" in data
        assert "ack_count" in data
        assert "total_ack_ms" in data
        
        print(f"✓ Session metrics for {TEST_SESSION_1}: sos_count={data['sos_count']}")


class TestDeliveryGateIntegration:
    """Tests for delivery gate integration with SOS flow"""

    def test_sos_not_allowlisted_simulator_mode(self):
        """POST /api/journey/sos with session NOT in allowlist shows delivery_guard.reason='simulator_mode'"""
        # Ensure emergency stop is released
        requests.post(f"{BASE_URL}/api/journey/rollout/emergency-release?actor=test_agent")
        
        # Remove session from allowlist if present
        requests.delete(f"{BASE_URL}/api/journey/rollout/allowlist/TEST_sos_not_allowlisted")
        
        # Trigger SOS
        sos_payload = {
            "sosId": f"TEST_sos_{int(time.time())}",
            "ts": int(time.time() * 1000),
            "riskScore": 50,
            "riskLevel": "high",
            "sessionId": "TEST_sos_not_allowlisted",
            "location": {"lat": 28.6, "lng": 77.2}
        }
        r = requests.post(f"{BASE_URL}/api/journey/sos", json=sos_payload)
        assert r.status_code == 200
        
        # Check notifications
        r2 = requests.get(f"{BASE_URL}/api/journey/notifications?limit=5")
        notifications = r2.json()["notifications"]
        
        # Find the notification for our SOS
        sos_notif = None
        for n in notifications:
            if n.get("sos_id") == sos_payload["sosId"]:
                sos_notif = n
                break
        
        assert sos_notif is not None, "SOS notification not found"
        assert "delivery_guard" in sos_notif, "Missing delivery_guard in notification"
        # Since JOURNEY_LIVE_DELIVERY=false, reason should be simulator_mode
        assert sos_notif["delivery_guard"]["reason"] == "simulator_mode", \
            f"Expected simulator_mode, got {sos_notif['delivery_guard']['reason']}"
        
        print(f"✓ SOS for non-allowlisted session: delivery_guard.reason='simulator_mode'")

    def test_sos_allowlisted_still_simulator_mode(self):
        """POST /api/journey/sos with allowlisted session still shows simulator_mode (because live_flag=false)"""
        # Ensure emergency stop is released
        requests.post(f"{BASE_URL}/api/journey/rollout/emergency-release?actor=test_agent")
        
        # Add session to allowlist
        requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={"session_id": "TEST_sos_allowlisted", "enabled": True, "stage": "stage1_internal"}
        )
        
        # Trigger SOS
        sos_payload = {
            "sosId": f"TEST_sos_al_{int(time.time())}",
            "ts": int(time.time() * 1000),
            "riskScore": 60,
            "riskLevel": "high",
            "sessionId": "TEST_sos_allowlisted",
            "location": {"lat": 28.6, "lng": 77.2}
        }
        r = requests.post(f"{BASE_URL}/api/journey/sos", json=sos_payload)
        assert r.status_code == 200
        
        # Check notifications
        r2 = requests.get(f"{BASE_URL}/api/journey/notifications?limit=5")
        notifications = r2.json()["notifications"]
        
        sos_notif = None
        for n in notifications:
            if n.get("sos_id") == sos_payload["sosId"]:
                sos_notif = n
                break
        
        assert sos_notif is not None, "SOS notification not found"
        # Even allowlisted, live_flag=false means simulator_mode
        assert sos_notif["delivery_guard"]["reason"] == "simulator_mode", \
            f"Expected simulator_mode (live_flag=false), got {sos_notif['delivery_guard']['reason']}"
        
        print(f"✓ SOS for allowlisted session: still simulator_mode (live_flag=false)")


class TestMetricsRecording:
    """Tests for metrics recording end-to-end"""

    def test_sos_records_metrics(self):
        """Trigger SOS and verify metrics are recorded"""
        session_id = "TEST_metrics_session"
        
        # Add to allowlist
        requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={"session_id": session_id, "enabled": True, "stage": "stage1_internal"}
        )
        
        # Get initial metrics
        r1 = requests.get(f"{BASE_URL}/api/journey/rollout/metrics/{session_id}")
        initial_sos = r1.json().get("sos_count", 0)
        
        # Trigger SOS
        sos_payload = {
            "sosId": f"TEST_metrics_{int(time.time())}",
            "ts": int(time.time() * 1000),
            "riskScore": 50,
            "riskLevel": "high",
            "sessionId": session_id,
            "location": {"lat": 28.6, "lng": 77.2}
        }
        r2 = requests.post(f"{BASE_URL}/api/journey/sos", json=sos_payload)
        assert r2.status_code == 200
        
        # Check metrics increased
        r3 = requests.get(f"{BASE_URL}/api/journey/rollout/metrics/{session_id}")
        new_sos = r3.json().get("sos_count", 0)
        
        assert new_sos > initial_sos, f"SOS count should increase: {initial_sos} -> {new_sos}"
        
        print(f"✓ SOS records metrics: sos_count {initial_sos} -> {new_sos}")


class TestDeliveryConfidence:
    """Tests for delivery confidence calculation"""

    def test_delivery_confidence_in_notification(self):
        """Verify delivery_confidence is present in notifications for delivered/acknowledged states"""
        session_id = "TEST_confidence_session"
        
        # Add to allowlist
        requests.post(
            f"{BASE_URL}/api/journey/rollout/allowlist",
            json={"session_id": session_id, "enabled": True, "stage": "stage1_internal"}
        )
        
        # Trigger SOS
        sos_id = f"TEST_conf_{int(time.time())}"
        sos_payload = {
            "sosId": sos_id,
            "ts": int(time.time() * 1000),
            "riskScore": 50,
            "riskLevel": "high",
            "sessionId": session_id,
            "location": {"lat": 28.6, "lng": 77.2}
        }
        requests.post(f"{BASE_URL}/api/journey/sos", json=sos_payload)
        
        # Check notifications for delivery_confidence
        r = requests.get(f"{BASE_URL}/api/journey/notifications?limit=10")
        notifications = r.json()["notifications"]
        
        # Find notification for our SOS with state 'delivered'
        delivered_notif = None
        for n in notifications:
            if n.get("sos_id") == sos_id and n.get("state") == "delivered":
                delivered_notif = n
                break
        
        assert delivered_notif is not None, "Delivered notification not found"
        # delivery_confidence should be present (may be 0 if no SMS/push success in simulator mode)
        assert "delivery_confidence" in delivered_notif, "Missing delivery_confidence in notification"
        
        print(f"✓ Delivery confidence present: {delivered_notif.get('delivery_confidence')}")


class TestCleanup:
    """Cleanup test data"""

    def test_cleanup_test_sessions(self):
        """Remove all TEST_ prefixed sessions from allowlist"""
        # Get all sessions
        r = requests.get(f"{BASE_URL}/api/journey/rollout/allowlist")
        sessions = r.json()["allowlist"]
        
        removed = 0
        for s in sessions:
            if s["session_id"].startswith("TEST_"):
                requests.delete(f"{BASE_URL}/api/journey/rollout/allowlist/{s['session_id']}")
                removed += 1
        
        # Ensure emergency stop is released
        requests.post(f"{BASE_URL}/api/journey/rollout/emergency-release?actor=test_cleanup")
        
        # Reset stage to stage1_internal
        requests.post(
            f"{BASE_URL}/api/journey/rollout/config",
            json={"current_stage": "stage1_internal", "actor": "test_cleanup"}
        )
        
        print(f"✓ Cleanup: removed {removed} test sessions, released emergency stop, reset stage")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
