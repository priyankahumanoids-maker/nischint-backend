"""REL-05 — Tests for the WebSocket leak audit sweeper.

What we lock down:
  1. Healthy sockets stay in `_cc_connections` after a sweep.
  2. A socket whose send raises `WebSocketDisconnect` is removed.
  3. A socket whose send raises any other Exception is removed.
  4. A socket whose `client_state != CONNECTED` is removed without
     even attempting a send.
  5. `sweep_dead_cc_connections` reports accurate counts.
  6. `cc_connections_count()` reflects the live set size.

We use a `_FakeWS` stand-in instead of a real Starlette WebSocket —
the sweeper's only contract with WebSocket is `client_state` +
`send_json`, both trivially mockable.
"""
from __future__ import annotations

import pytest
from fastapi import WebSocketDisconnect
from starlette.websockets import WebSocketState

import app.api.ws_command_center as cc


class _FakeWS:
    def __init__(self, *, state=WebSocketState.CONNECTED, raise_on_send=None):
        self.client_state = state
        self.raise_on_send = raise_on_send
        self.sent: list = []

    async def send_json(self, payload):
        if self.raise_on_send is not None:
            raise self.raise_on_send
        self.sent.append(payload)


@pytest.fixture(autouse=True)
def _isolate():
    """Reset the module-level set between tests so they don't pollute
    each other."""
    cc._cc_connections.clear()
    yield
    cc._cc_connections.clear()


@pytest.mark.asyncio
async def test_healthy_socket_survives_sweep():
    ws = _FakeWS()
    cc._cc_connections.add(ws)

    stats = await cc.sweep_dead_cc_connections()

    assert ws in cc._cc_connections
    assert stats == {"probed": 1, "removed": 0, "remaining": 1}
    # The sweeper sent exactly one ping frame with the expected shape.
    assert len(ws.sent) == 1
    assert ws.sent[0]["type"] == "ping"
    assert ws.sent[0]["source"] == "sweeper"


@pytest.mark.asyncio
async def test_disconnect_raises_socket_is_removed():
    healthy = _FakeWS()
    dead = _FakeWS(raise_on_send=WebSocketDisconnect(code=1006))
    cc._cc_connections.add(healthy)
    cc._cc_connections.add(dead)

    stats = await cc.sweep_dead_cc_connections()

    assert dead not in cc._cc_connections
    assert healthy in cc._cc_connections
    assert stats["removed"] == 1
    assert stats["remaining"] == 1


@pytest.mark.asyncio
async def test_arbitrary_exception_during_send_removes_socket():
    """Network-level RST or write-to-half-closed-socket should also
    drop the socket — never wait for the next broadcast to find it."""
    dead = _FakeWS(raise_on_send=RuntimeError("ECONNRESET"))
    cc._cc_connections.add(dead)

    stats = await cc.sweep_dead_cc_connections()

    assert dead not in cc._cc_connections
    assert stats["removed"] == 1
    assert stats["remaining"] == 0


@pytest.mark.asyncio
async def test_closed_state_socket_removed_without_send():
    """A socket Starlette already tore down (`client_state` ≠
    CONNECTED) must be reaped WITHOUT us touching it again. The
    pre-check is what makes the sweeper safe to run frequently —
    sending to a closed socket would raise inside Starlette's own
    internals."""
    dead = _FakeWS(state=WebSocketState.DISCONNECTED)
    cc._cc_connections.add(dead)

    stats = await cc.sweep_dead_cc_connections()

    assert dead not in cc._cc_connections
    # No `send_json` should have been attempted.
    assert dead.sent == []
    assert stats["removed"] == 1


@pytest.mark.asyncio
async def test_mixed_population_reports_correct_counts():
    healthy_1 = _FakeWS()
    healthy_2 = _FakeWS()
    dead_disc = _FakeWS(raise_on_send=WebSocketDisconnect(code=1006))
    dead_exc  = _FakeWS(raise_on_send=ConnectionError("RST"))
    dead_closed = _FakeWS(state=WebSocketState.DISCONNECTED)
    for ws in (healthy_1, healthy_2, dead_disc, dead_exc, dead_closed):
        cc._cc_connections.add(ws)

    stats = await cc.sweep_dead_cc_connections()

    assert stats == {"probed": 5, "removed": 3, "remaining": 2}
    assert {healthy_1, healthy_2} == set(cc._cc_connections)


@pytest.mark.asyncio
async def test_empty_set_returns_zero_counts():
    stats = await cc.sweep_dead_cc_connections()
    assert stats == {"probed": 0, "removed": 0, "remaining": 0}


@pytest.mark.asyncio
async def test_cc_connections_count_reflects_set_size():
    """The accessor exposed to monitoring/runtime-info must be the
    strict size of the set — no caching, no off-by-one."""
    assert cc.cc_connections_count() == 0
    cc._cc_connections.add(_FakeWS())
    assert cc.cc_connections_count() == 1
    cc._cc_connections.add(_FakeWS())
    cc._cc_connections.add(_FakeWS())
    assert cc.cc_connections_count() == 3
    cc._cc_connections.clear()
    assert cc.cc_connections_count() == 0


@pytest.mark.asyncio
async def test_iteration_safe_when_set_mutates_during_sweep():
    """The sweeper iterates `_cc_connections.copy()` so a concurrent
    `disconnect()` during a sweep can't trip 'set changed size during
    iteration'. We simulate by mutating the live set from inside a
    fake send_json."""
    target = _FakeWS()
    other = _FakeWS()

    async def fake_send_json(_payload):
        # Mid-sweep mutation: drop `other` while the sweeper is still
        # looking at us. Should not crash the sweep.
        cc._cc_connections.discard(other)

    target.send_json = fake_send_json  # type: ignore[assignment]

    cc._cc_connections.add(target)
    cc._cc_connections.add(other)

    # Must complete without raising.
    stats = await cc.sweep_dead_cc_connections()
    # Both probes happen (we iterated a snapshot), and the only
    # removal is the explicit discard inside fake_send_json (or, for
    # `other`, the pre-check if it's been dropped by the time we get
    # to it).
    assert stats["probed"] == 2
