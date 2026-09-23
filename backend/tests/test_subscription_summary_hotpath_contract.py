from pathlib import Path
import os


def _source() -> str:
    root = Path(os.environ.get("NISCHINT_BACKEND_ROOT", Path(__file__).resolve().parents[1]))
    return (root / "app/services/subscription_service.py").read_text(encoding="utf-8")


def test_summary_uses_single_read_hot_path_before_legacy_reconciliation():
    source = _source()
    start = source.index("async def summary_for_guardian")
    end = source.index("async def activate_test_subscription", start)
    body = source[start:end]
    first_read = body.index("_summary_rows_for_guardian(session, actor.id)")
    legacy = body.index("ensure_existing_members_premium(session, actor.id)")
    assert first_read < legacy
    assert "if not rows:" in body


def test_missing_table_bootstrap_is_preserved_without_hiding_other_db_errors():
    source = _source()
    start = source.index("async def summary_for_guardian")
    end = source.index("async def activate_test_subscription", start)
    body = source[start:end]
    assert '"member_subscriptions" not in message' in body
    assert "await session.rollback()" in body
    assert "await ensure_tables()" in body
    assert "raise" in body


def test_subscription_business_rules_are_unchanged():
    source = _source()
    assert 'PLAN_PRICES = {"standard": 299, "premium": 499}' in source
    assert '"protected_member_limit_per_subscription": 1' in source
    assert '"co_parent_included_per_subscription": 1' in source
    assert '"summary_runtime_version": "client-ready-v1"' in source
    assert '"wearable": premium' in source
    assert '"emergency_sos": True' in source
