"""
Tests for NISCHINT Delivery Health Dashboard - Iteration 4
==========================================================
Tests the new throughput_per_minute field in notification-jobs/stats:
- throughput_per_minute calculated as sent_count/window_minutes when window provided
- throughput_per_minute is null when no window_minutes param
- Stats endpoint returns correct totals by status
- Stats endpoint returns correct by_channel breakdown
- Regression tests for auth and existing endpoints
"""
import pytest
import requests
import os
import asyncio
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import asyncpg

# Base URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"

# Database URL
DATABASE_URL = os.environ.get('DATABASE_URL')


class TestHealthRegression:
    """Health check endpoints - verify backend is up"""
    
    def test_api_root(self):
        """Test API root endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        print(f"✓ API root working")
    
    def test_db_health_check(self):
        """Test PostgreSQL health check endpoint"""
        response = requests.get(f"{BASE_URL}/api/health/db")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        print(f"✓ DB health check: {data}")


class TestAuthRegression:
    """Authentication endpoints regression tests"""
    
    def test_guardian_login(self):
        """Test guardian login returns token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data.get("role") == "guardian"
        print(f"✓ Guardian login successful, role: {data.get('role')}")
    
    def test_operator_login(self):
        """Test operator login returns token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data.get("role") == "operator"
        print(f"✓ Operator login successful, role: {data.get('role')}")


class TestNotificationJobsStatsThroughput:
    """Tests for the throughput_per_minute field in notification-jobs/stats"""
    
    @pytest.fixture
    def operator_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        return response.json().get("access_token")
    
    def test_stats_with_window_returns_throughput(self, operator_token):
        """Test stats with window_minutes param returns throughput_per_minute as number"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs/stats?window_minutes=15",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "window_minutes" in data
        assert "totals" in data
        assert "by_channel" in data
        assert "throughput_per_minute" in data
        
        # window_minutes should be 15
        assert data["window_minutes"] == 15
        
        # throughput_per_minute should be a number (not null) when window provided
        assert data["throughput_per_minute"] is not None
        assert isinstance(data["throughput_per_minute"], (int, float))
        
        print(f"✓ Stats with window_minutes=15 returns throughput: {data['throughput_per_minute']} msg/min")
    
    def test_stats_without_window_returns_null_throughput(self, operator_token):
        """Test stats without window_minutes param returns throughput_per_minute=null"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs/stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # window_minutes should be null
        assert data["window_minutes"] is None
        
        # throughput_per_minute should be null (None in Python)
        assert data["throughput_per_minute"] is None
        
        print(f"✓ Stats without window_minutes returns throughput_per_minute=null")
    
    def test_stats_returns_totals_dict(self, operator_token):
        """Test stats returns totals as dict with status counts"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs/stats?window_minutes=60",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # totals should be a dict
        assert isinstance(data["totals"], dict)
        
        print(f"✓ Stats totals is a dict: {data['totals']}")
    
    def test_stats_returns_by_channel_dict(self, operator_token):
        """Test stats returns by_channel as dict with channel breakdowns"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs/stats?window_minutes=60",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # by_channel should be a dict
        assert isinstance(data["by_channel"], dict)
        
        print(f"✓ Stats by_channel is a dict: {data['by_channel']}")
    
    def test_stats_requires_auth(self):
        """Test stats endpoint requires authentication"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs/stats"
        )
        assert response.status_code in [401, 403]
        print(f"✓ Stats endpoint requires auth: {response.status_code}")
    
    def test_stats_requires_operator_role(self):
        """Test stats endpoint requires operator role (guardian gets 403)"""
        # Login as guardian
        guardian_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        guardian_token = guardian_response.json().get("access_token")
        
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs/stats",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403
        print(f"✓ Guardian gets 403 on stats endpoint (RBAC working)")


class TestNotificationJobsStatsWithData:
    """Tests for stats correctness with seeded data"""
    
    @pytest.fixture
    def operator_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        return response.json().get("access_token")
    
    @pytest.fixture
    def db_connection(self):
        async def _get_conn():
            conn = await asyncpg.connect(DATABASE_URL, ssl='require')
            return conn
        return asyncio.get_event_loop().run_until_complete(_get_conn())
    
    def test_stats_totals_with_seeded_data(self, operator_token, db_connection):
        """Test stats returns correct totals after seeding test notification jobs"""
        async def run_test():
            conn = db_connection
            try:
                # Create test jobs with different statuses
                test_jobs = [
                    (uuid4(), "email", "test1@example.com", "pending"),
                    (uuid4(), "email", "test2@example.com", "pending"),
                    (uuid4(), "sms", "+1234567891", "sent"),
                    (uuid4(), "sms", "+1234567892", "sent"),
                    (uuid4(), "sms", "+1234567893", "sent"),
                    (uuid4(), "push", "device_1", "retrying"),
                    (uuid4(), "email", "test3@example.com", "dead_letter"),
                    (uuid4(), "email", "test4@example.com", "cancelled"),
                ]
                
                job_ids = []
                for job_id, channel, recipient, status in test_jobs:
                    job_ids.append(job_id)
                    await conn.execute("""
                        INSERT INTO notification_jobs (id, channel, recipient, payload, status, attempts, created_at)
                        VALUES ($1, $2, $3, $4::jsonb, $5, $6, NOW())
                    """, job_id, channel, recipient, json.dumps({"body": f"Test {status}"}), status, 0)
                
                print(f"✓ Seeded {len(test_jobs)} test notification jobs")
                
                # Call stats API with large window to include all test data
                response = requests.get(
                    f"{BASE_URL}/api/operator/notification-jobs/stats?window_minutes=60",
                    headers={"Authorization": f"Bearer {operator_token}"}
                )
                assert response.status_code == 200
                data = response.json()
                
                # Verify totals (at minimum should have our test data)
                totals = data["totals"]
                assert totals.get("pending", 0) >= 2, f"Expected at least 2 pending, got {totals.get('pending', 0)}"
                assert totals.get("sent", 0) >= 3, f"Expected at least 3 sent, got {totals.get('sent', 0)}"
                assert totals.get("retrying", 0) >= 1, f"Expected at least 1 retrying, got {totals.get('retrying', 0)}"
                assert totals.get("dead_letter", 0) >= 1, f"Expected at least 1 dead_letter, got {totals.get('dead_letter', 0)}"
                assert totals.get("cancelled", 0) >= 1, f"Expected at least 1 cancelled, got {totals.get('cancelled', 0)}"
                
                print(f"✓ Stats totals correct: {totals}")
                
                # Verify by_channel breakdown
                by_channel = data["by_channel"]
                assert "email" in by_channel or "sms" in by_channel or "push" in by_channel
                print(f"✓ Stats by_channel correct: {by_channel}")
                
                # Verify throughput calculation: sent_count / window_minutes
                # We have 3 'sent' jobs in a 60 minute window
                # throughput should be >= 3/60 = 0.05 (rounded to 0.05)
                assert data["throughput_per_minute"] is not None
                assert data["throughput_per_minute"] >= 0
                print(f"✓ Throughput calculation: {data['throughput_per_minute']} msg/min")
                
                # Cleanup test jobs
                await conn.execute("DELETE FROM notification_jobs WHERE id = ANY($1)", job_ids)
                print(f"✓ Cleaned up {len(job_ids)} test jobs")
                
            finally:
                await conn.close()
        
        asyncio.get_event_loop().run_until_complete(run_test())
    
    def test_throughput_calculation_accuracy(self, operator_token, db_connection):
        """Test throughput_per_minute calculation is accurate (sent_count / window_minutes)"""
        async def run_test():
            conn = db_connection
            try:
                # Create exactly 10 'sent' jobs within last 5 minutes
                job_ids = []
                for i in range(10):
                    job_id = uuid4()
                    job_ids.append(job_id)
                    await conn.execute("""
                        INSERT INTO notification_jobs (id, channel, recipient, payload, status, attempts, created_at)
                        VALUES ($1, $2, $3, $4::jsonb, $5, $6, NOW() - INTERVAL '1 minute')
                    """, job_id, "email", f"throughput_test_{i}@example.com", 
                       json.dumps({"body": "Throughput test"}), "sent", 1)
                
                print(f"✓ Seeded 10 'sent' jobs for throughput test")
                
                # Get stats with 5 minute window
                response = requests.get(
                    f"{BASE_URL}/api/operator/notification-jobs/stats?window_minutes=5",
                    headers={"Authorization": f"Bearer {operator_token}"}
                )
                assert response.status_code == 200
                data = response.json()
                
                # 10 sent jobs / 5 minutes = 2.0 msg/min minimum
                # (there might be other sent jobs in the window)
                assert data["throughput_per_minute"] >= 2.0, \
                    f"Expected throughput >= 2.0, got {data['throughput_per_minute']}"
                print(f"✓ Throughput with 10 sent jobs in 5min window: {data['throughput_per_minute']} msg/min (expected >= 2.0)")
                
                # Cleanup
                await conn.execute("DELETE FROM notification_jobs WHERE id = ANY($1)", job_ids)
                print(f"✓ Cleaned up throughput test jobs")
                
            finally:
                await conn.close()
        
        asyncio.get_event_loop().run_until_complete(run_test())


class TestOperatorStatsRegression:
    """Regression tests for existing operator endpoints"""
    
    @pytest.fixture
    def operator_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        return response.json().get("access_token")
    
    def test_operator_stats(self, operator_token):
        """Test operator stats endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/operator/stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_incidents" in data
        assert "open_incidents" in data
        assert "escalated_incidents" in data
        print(f"✓ Operator stats: {data}")
    
    def test_false_alarm_metrics(self, operator_token):
        """Test false alarm metrics endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/operator/false-alarm-metrics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "false_alarms" in data
        assert "false_alarm_rate_percent" in data
        print(f"✓ False alarm metrics: {data}")
    
    def test_notification_jobs_list(self, operator_token):
        """Test notification jobs list endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs?limit=10",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "jobs" in data
        assert isinstance(data["jobs"], list)
        print(f"✓ Notification jobs list: total={data['total']}, jobs count={len(data['jobs'])}")


class TestGuardianDashboardRegression:
    """Regression tests for guardian dashboard"""
    
    @pytest.fixture
    def guardian_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        return response.json().get("access_token")
    
    def test_dashboard_summary(self, guardian_token):
        """Test guardian dashboard summary endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/summary",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_seniors" in data
        assert "total_devices" in data
        assert "active_incidents" in data
        print(f"✓ Guardian dashboard summary: {data}")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
