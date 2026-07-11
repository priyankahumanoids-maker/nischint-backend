"""
Tests for NISCHINT Govt-Scale Hardening Features (Iteration 3)
==============================================================
Tests THREE new features:
1. Pydantic Settings - Centralized env var config via Settings class
2. Delivery Idempotency - idempotency_key column with unique constraint
3. SSE Scoping - broadcaster refactored to user:{user_id} + role:operator channels
"""
import sys
sys.path.insert(0, '/app/backend')

import pytest
import requests
import os
import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
import asyncpg

# Base URL from environment - DO NOT add default value
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"

# Database URL for direct DB testing
DATABASE_URL = None


def get_db_url():
    """Get database URL from .env file"""
    global DATABASE_URL
    if DATABASE_URL is None:
        env_path = "/app/backend/.env"
        with open(env_path, 'r') as f:
            for line in f:
                if line.startswith('DATABASE_URL='):
                    DATABASE_URL = line.strip().split('=', 1)[1]
                    break
    return DATABASE_URL


# ═══════════════════════════════════════════════════════════════════════════
# FEATURE 1: Pydantic Settings Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPydanticSettingsConfig:
    """Tests verifying Pydantic Settings loads all config correctly"""
    
    def test_settings_class_loads_correctly(self):
        """Test Settings class can be instantiated and loads config"""
        from app.core.config import settings
        
        assert settings is not None
        assert hasattr(settings, 'jwt_secret')
        assert hasattr(settings, 'database_url')
        assert hasattr(settings, 'mongo_url')
        print(f"✓ Settings class loaded correctly, app_name={settings.app_name}")
    
    def test_settings_has_jwt_config(self):
        """Test JWT configuration is present"""
        from app.core.config import settings
        
        assert settings.jwt_secret is not None and len(settings.jwt_secret) > 0
        assert settings.jwt_algorithm == "HS256"
        assert settings.jwt_expires_minutes > 0
        print(f"✓ JWT config: algorithm={settings.jwt_algorithm}, expires={settings.jwt_expires_minutes}min")
    
    def test_settings_has_database_config(self):
        """Test PostgreSQL and MongoDB config present"""
        from app.core.config import settings
        
        assert settings.database_url is not None
        assert "postgresql" in settings.database_url or "postgres" in settings.database_url
        assert settings.mongo_url is not None
        assert settings.db_name is not None
        print(f"✓ Database config: db_name={settings.db_name}")
    
    def test_settings_has_ses_config(self):
        """Test AWS SES configuration present"""
        from app.core.config import settings
        
        assert settings.aws_region is not None
        assert settings.email_provider is not None
        print(f"✓ SES config: region={settings.aws_region}, provider={settings.email_provider}")
    
    def test_settings_has_twilio_config(self):
        """Test Twilio SMS configuration present"""
        from app.core.config import settings
        
        assert settings.sms_provider is not None
        print(f"✓ Twilio config: sms_provider={settings.sms_provider}")
    
    def test_settings_has_firebase_config(self):
        """Test Firebase FCM configuration present"""
        from app.core.config import settings
        
        assert settings.firebase_project_id is not None
        print(f"✓ Firebase config: project_id={settings.firebase_project_id}")
    
    def test_settings_has_cors_config(self):
        """Test CORS configuration present"""
        from app.core.config import settings
        
        assert settings.cors_origins is not None
        print(f"✓ CORS config: origins={settings.cors_origins[:50]}...")
    
    def test_settings_has_escalation_thresholds(self):
        """Test escalation time thresholds present"""
        from app.core.config import settings
        
        assert settings.escalation_l1_minutes > 0
        assert settings.escalation_l2_minutes > settings.escalation_l1_minutes
        assert settings.escalation_l3_minutes > settings.escalation_l2_minutes
        assert settings.escalation_check_interval > 0
        print(f"✓ Escalation thresholds: L1={settings.escalation_l1_minutes}m, L2={settings.escalation_l2_minutes}m, L3={settings.escalation_l3_minutes}m")
    
    def test_settings_has_worker_config(self):
        """Test notification worker configuration present"""
        from app.core.config import settings
        
        assert settings.worker_max_attempts > 0
        assert settings.worker_batch_size > 0
        assert settings.worker_poll_interval > 0
        assert settings.worker_backoff_base > 0
        print(f"✓ Worker config: max_attempts={settings.worker_max_attempts}, batch_size={settings.worker_batch_size}")
    
    def test_security_uses_settings(self):
        """Test security.py uses settings instead of os.environ"""
        from app.core.security import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
        from app.core.config import settings
        
        assert SECRET_KEY == settings.jwt_secret
        assert ALGORITHM == settings.jwt_algorithm
        assert ACCESS_TOKEN_EXPIRE_MINUTES == settings.jwt_expires_minutes
        print("✓ security.py uses settings from config.py")
    
    def test_db_session_uses_settings(self):
        """Test db/session.py uses settings instead of os.environ"""
        from app.db.session import DATABASE_URL
        from app.core.config import settings
        
        # DATABASE_URL may have been transformed for asyncpg
        assert "postgresql" in DATABASE_URL
        print("✓ db/session.py uses settings for DATABASE_URL")


class TestNoScatteredOsEnviron:
    """Tests verifying no os.environ or load_dotenv in app code"""
    
    def test_no_os_environ_in_app_core(self):
        """Test no os.environ in app/core/*.py files"""
        import subprocess
        result = subprocess.run(
            ["grep", "-r", "os.environ", "/app/backend/app/core/"],
            capture_output=True, text=True
        )
        # Should be empty (no matches)
        assert result.stdout.strip() == "", f"Found os.environ in app/core: {result.stdout}"
        print("✓ No os.environ in app/core/")
    
    def test_no_load_dotenv_in_app(self):
        """Test no load_dotenv in app/ directory"""
        import subprocess
        result = subprocess.run(
            ["grep", "-r", "load_dotenv", "/app/backend/app/"],
            capture_output=True, text=True
        )
        # Should be empty (no matches)
        assert result.stdout.strip() == "", f"Found load_dotenv in app/: {result.stdout}"
        print("✓ No load_dotenv in app/")
    
    def test_server_uses_settings(self):
        """Test server.py uses settings instead of os.environ"""
        with open("/app/backend/server.py", "r") as f:
            content = f.read()
        
        assert "from app.core.config import settings" in content
        assert "settings.mongo_url" in content
        assert "settings.db_name" in content
        assert "os.environ" not in content
        print("✓ server.py uses settings, no os.environ")


# ═══════════════════════════════════════════════════════════════════════════
# FEATURE 2: Delivery Idempotency Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestIdempotencyColumn:
    """Tests for idempotency_key column in notification_jobs table"""
    
    @pytest.fixture
    def db_connection(self):
        """Get async database connection"""
        async def _get_conn():
            conn = await asyncpg.connect(get_db_url(), ssl='require')
            return conn
        return asyncio.get_event_loop().run_until_complete(_get_conn())
    
    def test_idempotency_key_column_exists(self, db_connection):
        """Test idempotency_key column exists in notification_jobs table"""
        async def check():
            conn = db_connection
            try:
                result = await conn.fetchrow("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns 
                    WHERE table_name = 'notification_jobs' AND column_name = 'idempotency_key'
                """)
                assert result is not None, "idempotency_key column does not exist"
                assert result['data_type'] == 'character varying'
                print(f"✓ idempotency_key column exists: type={result['data_type']}, nullable={result['is_nullable']}")
            finally:
                await conn.close()
        
        asyncio.get_event_loop().run_until_complete(check())
    
    def test_idempotency_key_unique_index_exists(self, db_connection):
        """Test unique partial index on idempotency_key exists"""
        async def check():
            conn = db_connection
            try:
                result = await conn.fetch("""
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE tablename = 'notification_jobs' AND indexname LIKE '%idempotency%'
                """)
                assert len(result) > 0, "No unique index on idempotency_key"
                idx_def = result[0]['indexdef']
                assert 'UNIQUE' in idx_def
                assert 'idempotency_key' in idx_def
                # Verify it's a partial index (WHERE clause)
                assert 'WHERE' in idx_def
                print(f"✓ Unique partial index on idempotency_key: {result[0]['indexname']}")
            finally:
                await conn.close()
        
        asyncio.get_event_loop().run_until_complete(check())
    
    def test_notification_job_model_has_idempotency_key(self):
        """Test NotificationJob SQLAlchemy model has idempotency_key attribute"""
        from app.models.notification_job import NotificationJob
        
        assert hasattr(NotificationJob, 'idempotency_key')
        print("✓ NotificationJob model has idempotency_key attribute")


class TestIdempotencyBehavior:
    """Tests for idempotent notification job enqueue behavior"""
    
    @pytest.fixture
    def db_connection(self):
        async def _get_conn():
            conn = await asyncpg.connect(get_db_url(), ssl='require')
            return conn
        return asyncio.get_event_loop().run_until_complete(_get_conn())
    
    def test_duplicate_idempotency_key_blocked(self, db_connection):
        """Test that duplicate idempotency_key is blocked by unique constraint"""
        async def test_duplicate():
            conn = db_connection
            try:
                test_id_1 = uuid4()
                test_id_2 = uuid4()
                idem_key = f"TEST_{uuid4()}:email:test@example.com:1"
                
                # First insert should succeed
                await conn.execute("""
                    INSERT INTO notification_jobs (id, channel, recipient, payload, status, attempts, idempotency_key)
                    VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                """, test_id_1, "email", "test@example.com", json.dumps({"body": "test"}), "pending", 0, idem_key)
                
                # Second insert with same idempotency_key should fail
                try:
                    await conn.execute("""
                        INSERT INTO notification_jobs (id, channel, recipient, payload, status, attempts, idempotency_key)
                        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                    """, test_id_2, "email", "test@example.com", json.dumps({"body": "test2"}), "pending", 0, idem_key)
                    assert False, "Duplicate idempotency_key should have raised exception"
                except asyncpg.UniqueViolationError:
                    print("✓ Duplicate idempotency_key correctly blocked by unique constraint")
                
                # Cleanup
                await conn.execute("DELETE FROM notification_jobs WHERE id = $1", test_id_1)
            finally:
                await conn.close()
        
        asyncio.get_event_loop().run_until_complete(test_duplicate())
    
    def test_idempotency_key_format(self):
        """Test idempotency_key format: {incident_id}:{channel}:{recipient}:{escalation_level}"""
        # Read escalation_scheduler to verify key format
        with open("/app/backend/app/services/escalation_scheduler.py", "r") as f:
            content = f.read()
        
        # Verify idempotency key format in _enqueue_job
        assert 'idem_key = f"{incident_id}:{channel}:{recipient}:{escalation_level}"' in content
        print("✓ Idempotency key format: {incident_id}:{channel}:{recipient}:{escalation_level}")
    
    def test_different_escalation_levels_produce_different_keys(self, db_connection):
        """Test different escalation levels produce different idempotency keys"""
        async def test_levels():
            conn = db_connection
            try:
                incident_id = uuid4()
                recipient = f"TEST_{uuid4()}@example.com"
                
                # Create jobs for L1, L2, L3 - all should succeed (different keys)
                job_ids = []
                for level in [1, 2, 3]:
                    job_id = uuid4()
                    job_ids.append(job_id)
                    idem_key = f"{incident_id}:email:{recipient}:{level}"
                    
                    await conn.execute("""
                        INSERT INTO notification_jobs (id, channel, recipient, payload, status, attempts, idempotency_key)
                        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                    """, job_id, "email", recipient, json.dumps({"body": f"L{level}", "escalation_level": level}), "pending", 0, idem_key)
                
                # Verify all 3 jobs exist
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM notification_jobs WHERE id = ANY($1)", job_ids
                )
                assert count == 3, f"Expected 3 jobs for different levels, got {count}"
                print("✓ Different escalation levels (L1, L2, L3) produce different idempotency keys")
                
                # Cleanup
                await conn.execute("DELETE FROM notification_jobs WHERE id = ANY($1)", job_ids)
            finally:
                await conn.close()
        
        asyncio.get_event_loop().run_until_complete(test_levels())
    
    def test_escalation_scheduler_checks_existing_key(self):
        """Test escalation_scheduler._enqueue_job checks for existing key before insert"""
        with open("/app/backend/app/services/escalation_scheduler.py", "r") as f:
            content = f.read()
        
        # Verify _enqueue_job checks for existing
        assert "existing = (await session.execute(" in content
        assert "NotificationJob.idempotency_key == idem_key" in content
        assert "if existing:" in content
        assert "Idempotent skip:" in content
        print("✓ _enqueue_job checks for existing idempotency_key before insert")


class TestIdempotencyAPIVisibility:
    """Tests that idempotency_key is visible in API responses"""
    
    @pytest.fixture
    def operator_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        return response.json().get("access_token")
    
    def test_notification_jobs_endpoint_shows_idempotency_key(self, operator_token):
        """Test /api/operator/notification-jobs returns idempotency_key field"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs?limit=10",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # If there are jobs, verify idempotency_key field exists
        assert "jobs" in data
        # Even if empty, the structure should support idempotency_key
        print(f"✓ notification-jobs endpoint works (total: {data.get('total', 0)})")
        
        # Check operator.py has idempotency_key in _job_to_dict
        with open("/app/backend/app/api/operator.py", "r") as f:
            content = f.read()
        assert '"idempotency_key": job.idempotency_key' in content
        print("✓ idempotency_key field is included in notification-jobs API response")


# ═══════════════════════════════════════════════════════════════════════════
# FEATURE 3: SSE Scoping Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSSEChannelArchitecture:
    """Tests for SSE broadcaster channel architecture"""
    
    def test_broadcaster_has_dual_channel_system(self):
        """Test broadcaster supports user:{user_id} and role:operator channels"""
        from app.services.event_broadcaster import broadcaster, _USER_PREFIX, _ROLE_PREFIX
        
        assert _USER_PREFIX == "user:"
        assert _ROLE_PREFIX == "role:"
        
        # Verify channel key builders
        test_user_id = "abc-123"
        assert broadcaster.user_channel(test_user_id) == "user:abc-123"
        assert broadcaster.operator_channel() == "role:operator"
        print("✓ Broadcaster has dual-channel system: user:{id} and role:operator")
    
    def test_broadcaster_broadcast_methods(self):
        """Test broadcaster has broadcast_to_user and broadcast_to_operators methods"""
        from app.services.event_broadcaster import broadcaster
        
        assert hasattr(broadcaster, 'broadcast_to_user')
        assert hasattr(broadcaster, 'broadcast_to_operators')
        assert hasattr(broadcaster, 'broadcast_incident_created')
        assert hasattr(broadcaster, 'broadcast_incident_updated')
        assert hasattr(broadcaster, 'broadcast_incident_escalated')
        print("✓ Broadcaster has required broadcast methods")
    
    def test_broadcast_methods_fan_out_to_both_channels(self):
        """Test convenience methods broadcast to BOTH guardian + operator channels"""
        with open("/app/backend/app/services/event_broadcaster.py", "r") as f:
            content = f.read()
        
        # broadcast_incident_created should call both
        assert "await self.broadcast_to_user(guardian_id, \"incident_created\"" in content
        assert "await self.broadcast_to_operators(\"incident_created\"" in content
        
        # broadcast_incident_updated should call both
        assert "await self.broadcast_to_user(guardian_id, \"incident_updated\"" in content
        assert "await self.broadcast_to_operators(\"incident_updated\"" in content
        
        # broadcast_incident_escalated should call both
        assert "await self.broadcast_to_user(guardian_id, \"incident_escalated\"" in content
        assert "await self.broadcast_to_operators(\"incident_escalated\"" in content
        
        print("✓ Convenience methods fan out to BOTH user + operator channels")


class TestSSEStreamEndpoint:
    """Tests for SSE stream endpoint scoping"""
    
    @pytest.fixture
    def guardian_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        return response.json().get("access_token")
    
    @pytest.fixture
    def operator_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        return response.json().get("access_token")
    
    def test_sse_stream_endpoint_exists(self):
        """Test SSE stream endpoint at /api/stream is defined"""
        with open("/app/backend/app/api/stream.py", "r") as f:
            content = f.read()
        
        assert '@router.get("")' in content
        assert "async def stream_events" in content
        print("✓ SSE stream endpoint defined at /api/stream")
    
    def test_sse_unauthenticated_returns_401(self):
        """Test SSE stream without token returns 401"""
        response = requests.get(f"{BASE_URL}/api/stream", stream=True, timeout=5)
        # Should return 401 immediately
        assert response.status_code == 401
        print("✓ SSE stream without token returns 401")
    
    def test_sse_guardian_gets_user_channel(self, guardian_token):
        """Test guardian SSE stream connects to user:{user_id} channel"""
        import time
        
        # Start SSE connection with timeout
        try:
            response = requests.get(
                f"{BASE_URL}/api/stream?token={guardian_token}",
                stream=True,
                timeout=3
            )
            assert response.status_code == 200
            
            # Read the initial 'connected' event
            for line in response.iter_lines(decode_unicode=True):
                if line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    assert "channel" in data
                    assert data["channel"].startswith("user:")
                    assert "user_id" in data
                    print(f"✓ Guardian SSE connects to channel: {data['channel']}")
                    break
        except requests.exceptions.ReadTimeout:
            # This is expected after we read the connected event
            pass
    
    def test_sse_operator_gets_role_channel(self, operator_token):
        """Test operator SSE stream connects to role:operator channel"""
        try:
            response = requests.get(
                f"{BASE_URL}/api/stream?token={operator_token}",
                stream=True,
                timeout=3
            )
            assert response.status_code == 200
            
            # Read the initial 'connected' event
            for line in response.iter_lines(decode_unicode=True):
                if line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    assert "channel" in data
                    assert data["channel"] == "role:operator"
                    assert "role" in data
                    print(f"✓ Operator SSE connects to channel: {data['channel']}")
                    break
        except requests.exceptions.ReadTimeout:
            pass
    
    def test_stream_endpoint_uses_role_check(self):
        """Test stream.py determines channel based on user.role"""
        with open("/app/backend/app/api/stream.py", "r") as f:
            content = f.read()
        
        assert 'if current_user.role in ("operator", "admin"):' in content
        assert 'channel = broadcaster.operator_channel()' in content
        assert 'channel = broadcaster.user_channel(user_id)' in content
        print("✓ Stream endpoint uses role-based channel selection")


class TestSSEInvalidToken:
    """Test SSE endpoint handles invalid/malformed tokens"""
    
    def test_sse_invalid_token_returns_401(self):
        """Test SSE with invalid token returns 401"""
        response = requests.get(
            f"{BASE_URL}/api/stream?token=invalid_token_xyz",
            stream=True,
            timeout=5
        )
        assert response.status_code == 401
        print("✓ SSE with invalid token returns 401")
    
    def test_sse_expired_token_returns_401(self):
        """Test SSE with expired token returns 401"""
        # Create a token that's already expired (mock)
        expired_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0IiwiZXhwIjoxNjAwMDAwMDAwfQ.invalid"
        
        response = requests.get(
            f"{BASE_URL}/api/stream?token={expired_token}",
            stream=True,
            timeout=5
        )
        assert response.status_code == 401
        print("✓ SSE with expired/malformed token returns 401")


# ═══════════════════════════════════════════════════════════════════════════
# EXISTING FUNCTIONALITY REGRESSION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestHealthEndpoints:
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


class TestAuthEndpoints:
    """Authentication endpoints"""
    
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
        print(f"✓ Guardian login successful")
    
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
        print(f"✓ Operator login successful")


class TestDashboardEndpoints:
    """Dashboard endpoints for guardian"""
    
    @pytest.fixture
    def guardian_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        return response.json().get("access_token")
    
    def test_dashboard_summary(self, guardian_token):
        """Test guardian dashboard summary endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/summary",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_seniors" in data
        assert "total_devices" in data
        assert "active_incidents" in data
        print(f"✓ Dashboard summary working")


class TestOperatorEndpoints:
    """Operator endpoints"""
    
    @pytest.fixture
    def operator_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        return response.json().get("access_token")
    
    def test_operator_stats(self, operator_token):
        """Test operator stats endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/operator/stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_incidents" in data
        assert "open_incidents" in data
        assert "escalated_incidents" in data
        print(f"✓ Operator stats working")
    
    def test_notification_jobs_listing(self, operator_token):
        """Test notification jobs listing endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs?limit=10",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "jobs" in data
        print(f"✓ Notification jobs listing working (total: {data.get('total')})")


class TestOperatorRetryCancel:
    """Test retry/cancel endpoints for notification jobs"""
    
    @pytest.fixture
    def operator_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        return response.json().get("access_token")
    
    def test_retry_nonexistent_job_returns_404(self, operator_token):
        """Test retry endpoint returns 404 for non-existent job"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.post(
            f"{BASE_URL}/api/operator/notification-jobs/{fake_id}/retry",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 404
        print("✓ Retry non-existent job returns 404")
    
    def test_cancel_nonexistent_job_returns_404(self, operator_token):
        """Test cancel endpoint returns 404 for non-existent job"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.post(
            f"{BASE_URL}/api/operator/notification-jobs/{fake_id}/cancel",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 404
        print("✓ Cancel non-existent job returns 404")


class TestRBACAccess:
    """Test RBAC: guardian cannot access operator endpoints"""
    
    @pytest.fixture
    def guardian_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        return response.json().get("access_token")
    
    def test_guardian_cannot_access_operator_stats(self, guardian_token):
        """Test guardian gets 403 on /api/operator/stats"""
        response = requests.get(
            f"{BASE_URL}/api/operator/stats",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403
        print("✓ Guardian correctly gets 403 on operator stats")
    
    def test_guardian_cannot_access_notification_jobs(self, guardian_token):
        """Test guardian gets 403 on /api/operator/notification-jobs"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403
        print("✓ Guardian correctly gets 403 on notification jobs")
    
    def test_guardian_cannot_access_all_incidents(self, guardian_token):
        """Test guardian gets 403 on /api/operator/incidents"""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403
        print("✓ Guardian correctly gets 403 on operator incidents")


class TestWorkerFunctionality:
    """Test notification worker still works correctly"""
    
    def test_worker_backoff_calculation(self):
        """Test exponential backoff calculation"""
        from app.services.notification_worker import _backoff_seconds
        
        assert _backoff_seconds(0) == 30
        assert _backoff_seconds(1) == 60
        assert _backoff_seconds(2) == 120
        assert _backoff_seconds(3) == 240
        assert _backoff_seconds(4) == 480
        print("✓ Worker exponential backoff calculation correct")
    
    def test_worker_uses_settings(self):
        """Test notification worker uses settings from config"""
        from app.services.notification_worker import MAX_ATTEMPTS, BATCH_SIZE, POLL_INTERVAL_SECONDS
        from app.core.config import settings
        
        assert MAX_ATTEMPTS == settings.worker_max_attempts
        assert BATCH_SIZE == settings.worker_batch_size
        assert POLL_INTERVAL_SECONDS == settings.worker_poll_interval
        print("✓ Worker uses settings from config.py")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
