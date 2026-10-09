"""Offline Redis blocking regressions; python -B, no server/DB/provider startup."""
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(relative):
    name = "isolated_" + relative.replace("/", "_").replace(".", "_") + str(time.monotonic_ns())
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def event(job="job"):
    return types.SimpleNamespace(job_id=job, scheduled_run_times=[datetime.now(timezone.utc)],
                                 retval={"_duration_ms": 2}, exception=ValueError("synthetic"))


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_callbacks_health_lock_and_bounded_coalescing(self):
        from fastapi import FastAPI
        import httpx
        sm = load("app/services/scheduler_metrics.py")
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        tids, acquired = [], []
        class FakeRedis:
            def set(self, *args, **kwargs):
                tids.append(threading.get_ident())
                ok = sm._lock.acquire(blocking=False)
                acquired.append(ok)
                if ok: sm._lock.release()
                entered.set()
                release.wait(3)
            def sadd(self, *args): pass
        sm._redis = lambda: FakeRedis()
        sm._maybe_emit_threshold_event = lambda job: finished.set()
        app = FastAPI()
        @app.get("/health")
        async def health(): return {"status": "ok"}
        try:
            sm._on_submitted(event(), "test")
            for _ in range(100):
                if entered.is_set(): break
                await asyncio.sleep(.005)
            self.assertTrue(entered.is_set())
            worker = sm._telemetry_worker
            start = time.monotonic()
            for callback in [sm._on_executed, sm._on_error, sm._on_missed, sm._on_submitted]:
                callback(event(), "test")
            for _ in range(1000): sm._on_executed(event(), "test")
            for i in range(400): sm._on_submitted(event(str(i)), "test")
            self.assertLess(time.monotonic() - start, .5)
            self.assertIs(worker, sm._telemetry_worker)
            self.assertEqual(sm._stats["job"].success_count, 1001)
            self.assertEqual(sm._stats["job"].error_count, 1)
            self.assertEqual(sm._stats["job"].missed_count, 1)
            with sm._pending_condition:
                self.assertLessEqual(len(sm._pending), sm._PENDING_LIMIT)
                self.assertGreater(sm._dropped_snapshots, 0)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
                response = await asyncio.wait_for(client.get("/health"), .5)
                self.assertEqual(response.json(), {"status": "ok"})
            ticks = 0
            for _ in range(3):
                await asyncio.sleep(.01)
                ticks += 1
            self.assertEqual(ticks, 3)
            self.assertTrue(all(acquired))
            self.assertNotIn(threading.get_ident(), tids)
        finally:
            release.set()
            await asyncio.to_thread(finished.wait, 2)

    async def test_snapshot_is_detached_and_same_job_coalesces(self):
        sm = load("app/services/scheduler_metrics.py")
        sm._telemetry_worker = types.SimpleNamespace(is_alive=lambda: True)
        sm._on_submitted(event(), "test")
        first = sm._pending["job"]
        sm._on_submitted(event(), "test")
        self.assertEqual(len(first.drifts_ms), 1)
        self.assertEqual(len(sm._pending), 1)
        self.assertEqual(len(sm._pending["job"].drifts_ms), 2)

    async def test_threshold_runs_on_worker_once_for_batch(self):
        sm = load("app/services/scheduler_metrics.py")
        sm._telemetry_worker = types.SimpleNamespace(is_alive=lambda: True)
        for i in range(10): sm._on_executed(event(str(i)), "test")
        done = threading.Event(); calls = []; persisted = []
        sm._persist = lambda snapshot: persisted.append(snapshot.job_id)
        sm._maybe_emit_threshold_event = lambda job: (calls.append(threading.get_ident()), done.set())
        worker = threading.Thread(target=sm._telemetry_loop, daemon=True)
        worker.start()
        self.assertTrue(await asyncio.to_thread(done.wait, 1))
        self.assertEqual(len(persisted), 10)
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0], threading.get_ident())


class LimiterTests(unittest.IsolatedAsyncioTestCase):
    def module(self):
        with patch.dict(os.environ, {"REDIS_URL": "rediss://synthetic.invalid:6379"}):
            return load("app/core/rate_limiter.py")

    async def test_actual_dependency_timeout_and_retry_options(self):
        m = self.module()
        pool = m.limiter._storage.storage.connection_pool
        c = pool.connection_class(**pool.connection_kwargs)  # no connect
        self.assertEqual(c.socket_timeout, 1.0)
        self.assertEqual(c.socket_connect_timeout, 1.0)
        self.assertEqual(c.retry._retries, 0)
        self.assertFalse(c.retry_on_timeout)
        self.assertTrue(m.limiter._in_memory_fallback_enabled)

    async def test_url_query_cannot_override_http_timeout_bounds(self):
        with patch.dict(os.environ, {"REDIS_URL": "rediss://synthetic.invalid:6379/2?socket_timeout=60&socket_connect_timeout=60&retry_on_timeout=True"}):
            m = load("app/core/rate_limiter.py")
        pool = m.limiter._storage.storage.connection_pool
        self.assertEqual(pool.connection_kwargs["socket_timeout"], 1.0)
        self.assertEqual(pool.connection_kwargs["socket_connect_timeout"], 1.0)
        self.assertFalse(pool.connection_kwargs["retry_on_timeout"])
        self.assertEqual(pool.connection_kwargs["db"], 2)

    async def test_general_storage_failure_falls_back_and_enforces_budget(self):
        from fastapi import FastAPI, Request
        from slowapi.errors import RateLimitExceeded
        m = self.module(); lim = m.limiter
        @lim.limit("1/minute")
        async def endpoint(request: Request): pass
        app = FastAPI(); app.state.limiter = lim
        scope = {"type": "http", "method": "GET", "path": "/limited", "headers": [],
                 "app": app, "client": ("local", 1)}
        lim._limiter.hit = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("synthetic"))
        lim._storage.check = lambda: False
        lim._check_request_limit(Request(scope), endpoint, False)
        self.assertTrue(lim._storage_dead)
        with self.assertRaises(RateLimitExceeded):
            lim._check_request_limit(Request(scope), endpoint, False)

    async def test_strict_otp_loss_is_503(self):
        from fastapi import HTTPException
        m = self.module()
        fake = types.ModuleType("app.services.redis_service"); fake._get_client = lambda: None
        with patch.dict(sys.modules, {"app.services.redis_service": fake}):
            with self.assertRaises(HTTPException) as caught:
                await m.enforce_otp_limit(types.SimpleNamespace(client=types.SimpleNamespace(host="local")),
                                         identity="synthetic", purpose="phone_login", operation="issue", key="synthetic-key")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.headers["Retry-After"], "30")


class BroadcasterTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_ping_local_delivery_and_heartbeat(self):
        m = load("app/services/event_broadcaster.py"); b = m.EventBroadcaster()
        b._redis_listener_started = True
        q = await b.subscribe("user:synthetic")
        entered, release = threading.Event(), threading.Event()
        tids = []; sent = []
        def available():
            tids.append(threading.get_ident()); entered.set(); release.wait(3); return True
        fake = types.ModuleType("app.services.redis_service")
        fake.is_available = available
        fake.publish_event = lambda channel, payload: (sent.append((channel, payload)), True)[1]
        with patch.dict(sys.modules, {"app.services.redis_service": fake}):
            task = asyncio.create_task(b._publish("user:synthetic", "emergency_triggered", {"test": True}))
            try:
                local = await asyncio.wait_for(q.get(), .5)
                self.assertEqual(local["type"], "emergency_triggered")
                for _ in range(100):
                    if entered.is_set(): break
                    await asyncio.sleep(.005)
                self.assertTrue(entered.is_set())
                await asyncio.wait_for(asyncio.sleep(.02), .2)
                self.assertFalse(task.done())
                self.assertNotEqual(tids[0], threading.get_ident())
                release.set(); await task
                self.assertEqual(sent[0][1], local)
                self.assertEqual(sent[0][0], m._REDIS_PUBSUB_CHANNEL)
                self.assertEqual((await b.get_replay_events("user:synthetic"))[0], local)
            finally:
                release.set(); await task

    async def test_unavailable_redis_keeps_local_event(self):
        m = load("app/services/event_broadcaster.py"); b = m.EventBroadcaster()
        b._redis_listener_started = True; q = await b.subscribe("user:synthetic")
        fake = types.ModuleType("app.services.redis_service")
        fake.is_available = lambda: False
        fake.publish_event = lambda *a: self.fail("must not publish unavailable")
        with patch.dict(sys.modules, {"app.services.redis_service": fake}):
            await b._publish("user:synthetic", "emergency_triggered", {})
        self.assertEqual((await q.get())["type"], "emergency_triggered")


if __name__ == "__main__":
    unittest.main()
