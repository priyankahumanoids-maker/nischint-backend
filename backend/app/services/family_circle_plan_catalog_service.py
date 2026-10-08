"""Runtime Family Circle plan catalog authority for R2.

Operational seat/capability metadata is read from ``family_plan_catalog``.  The
v1.1 current plan keys remain stable, but limits and feature metadata are data so
future configuration changes do not require duplicating capacities in callers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class CatalogPlan:
    plan: str
    display_name: str
    price_inr: int
    billing_period: str
    trial_days: int | None
    capacities: dict[str, int]
    features: dict[str, Any]
    sort_order: int


def _dict(value) -> dict:
    return dict(value) if isinstance(value, dict) else {}


async def get_catalog_plan(session: AsyncSession, plan: str) -> CatalogPlan:
    key = str(plan or '').strip().lower()
    row = (await session.execute(text("""
        SELECT plan_key, display_name, price_inr, billing_period, trial_days,
               seat_capacities, feature_flags, sort_order
          FROM family_plan_catalog
         WHERE plan_key=:plan AND active=TRUE
    """), {"plan": key})).mappings().first()
    if not row:
        raise ValueError("Family Circle plan configuration is unavailable.")
    capacities = {str(k): int(v) for k, v in _dict(row['seat_capacities']).items()}
    if not capacities or any(v < 1 for v in capacities.values()):
        raise ValueError("Family Circle plan seat configuration is invalid.")
    return CatalogPlan(
        plan=str(row['plan_key']),
        display_name=str(row['display_name']),
        price_inr=int(row['price_inr']),
        billing_period=str(row['billing_period']),
        trial_days=int(row['trial_days']) if row['trial_days'] is not None else None,
        capacities=capacities,
        features=_dict(row['feature_flags']),
        sort_order=int(row['sort_order'] or 0),
    )


async def list_catalog_plans(session: AsyncSession) -> list[CatalogPlan]:
    rows = (await session.execute(text("""
        SELECT plan_key, display_name, price_inr, billing_period, trial_days,
               seat_capacities, feature_flags, sort_order
          FROM family_plan_catalog
         WHERE active=TRUE
         ORDER BY sort_order, plan_key
    """))).mappings().all()
    plans: list[CatalogPlan] = []
    for row in rows:
        capacities = {str(k): int(v) for k, v in _dict(row['seat_capacities']).items()}
        if not capacities or any(v < 1 for v in capacities.values()):
            continue
        plans.append(CatalogPlan(
            plan=str(row['plan_key']), display_name=str(row['display_name']),
            price_inr=int(row['price_inr']), billing_period=str(row['billing_period']),
            trial_days=int(row['trial_days']) if row['trial_days'] is not None else None,
            capacities=capacities, features=_dict(row['feature_flags']),
            sort_order=int(row['sort_order'] or 0),
        ))
    return plans


def public_plan_payload(plan: CatalogPlan) -> dict:
    seats = plan.capacities
    if 'member' in seats:
        seat_label = f"{seats['member']} members total"
    else:
        seat_label = f"{seats.get('protected', 0)} Protected + up to {seats.get('guardian', 0)} Guardians"
    if plan.billing_period == 'trial':
        price_label = f"₹{plan.price_inr} for {plan.trial_days or 7} days"
    else:
        price_label = f"₹{plan.price_inr}/{plan.billing_period}"
    return {
        'id': plan.plan,
        'title': plan.display_name,
        'price_inr': plan.price_inr,
        'price_label': price_label,
        'billing_period': plan.billing_period,
        'trial_days': plan.trial_days,
        'seat_capacities': dict(plan.capacities),
        'seat_label': seat_label,
        'features': dict(plan.features),
    }


__all__ = ['CatalogPlan', 'get_catalog_plan', 'list_catalog_plans', 'public_plan_payload']
