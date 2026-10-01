"""Payment-provider-neutral Phase 6 billing contract.

No live Razorpay calls are made here. A future Razorpay adapter must verify the
provider signature first, then create ``VerifiedBillingEvent`` and hand it to
the entitlement service. App callbacks can never create this object implicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

BILLING_EVENT_TYPES = frozenset({
    'payment_activated',
    'renewal_succeeded',
    'renewal_failed',
    'period_ended',
    'cancel_scheduled',
    'upgrade_succeeded',
    'downgrade_scheduled',
    'downgrade_effective',
})


@dataclass(frozen=True)
class VerifiedBillingEvent:
    provider: str
    provider_event_id: str
    event_type: str
    effective_at: datetime
    payload_digest: str
    current_period_end: datetime | None = None
    target_plan: str | None = None

    def __post_init__(self):
        provider = str(self.provider or '').strip()
        if not provider or len(provider) > 24:
            raise ValueError('A stable billing provider id is required.')
        if self.event_type not in BILLING_EVENT_TYPES:
            raise ValueError('Unsupported verified billing event type.')
        if not self.provider_event_id or len(self.provider_event_id) > 180:
            raise ValueError('A stable provider event id is required.')
        digest = str(self.payload_digest or '').lower()
        if len(digest) != 64 or any(ch not in '0123456789abcdef' for ch in digest):
            raise ValueError('Verified billing payload digest must be SHA-256 hex.')
        if self.effective_at.tzinfo is None:
            raise ValueError('Verified billing event time must be timezone-aware.')


class BillingProviderAdapter(Protocol):
    """Future provider adapter boundary. No implementation is enabled in Phase 6."""

    async def verify_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> VerifiedBillingEvent:
        ...


__all__ = ['BILLING_EVENT_TYPES', 'VerifiedBillingEvent', 'BillingProviderAdapter']
