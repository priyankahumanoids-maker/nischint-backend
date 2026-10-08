from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def read(rel): return (ROOT / rel).read_text(encoding='utf-8')


def test_r2_plan_catalog_is_data_backed_and_migration_chains_after_r1():
    mig = read('migrations/versions/fc09_r2_plan_catalog.py')
    svc = read('app/services/family_circle_plan_catalog_service.py')
    plans = read('app/services/family_circle_plan_service.py')
    assert 'down_revision = "fc08_r1_lifecycle"' in mig
    assert 'CREATE TABLE family_plan_catalog' in mig
    assert "('trial', '7-day Free Trial', 0" in mig
    assert "('individual', 'Individual', 299" in mig
    assert "('family', 'Family', 999" in mig
    assert 'FROM family_plan_catalog' in svc
    assert 'get_runtime_plan_shape' in plans
    assert 'runtime_seat_capacity' in plans


def test_r2_operational_capacity_callers_use_runtime_catalog():
    invite = read('app/services/family_circle_invite_service.py')
    manage = read('app/services/family_circle_management_service.py')
    assert 'await runtime_seat_capacity' in invite
    assert 'await get_runtime_plan_shape' in invite
    assert 'await runtime_seat_capacity' in manage


def test_r2_trial_reminders_use_existing_outbox_and_worker():
    reminder = read('app/services/family_circle_trial_reminder_service.py')
    worker = read('app/services/notification_worker.py')
    assert "day not in {5, 6, 7}" in reminder
    assert 'enqueue_family_notifications' in reminder
    assert 'trial-reminder:' in reminder
    assert 'enqueue_due_trial_reminders' in worker
    assert 'drain_family_notifications' in worker


def test_r2_plan_transition_api_never_activates_unverified_payment():
    api = read('app/api/family_circle_phase6.py')
    plans = read('app/services/family_circle_plan_change_service.py')
    assert "/plan-change/prepare-family" in api
    assert "/plan-change/stage-individual" in api
    assert "state': 'provider_action_required'" in plans
    assert "plan_changed': False" in plans
    assert 'payment-success' not in api
    assert 'import razorpay' not in (api + plans).lower()


def test_r2_lifeline_and_trial_metadata_are_exposed_without_safety_engine_changes():
    api = read('app/api/family_circle_phase6.py')
    assert "'trial_remaining_seconds'" in api
    assert "'trial_day'" in api
    assert "'plan_config'" in api
    assert "'can_manage_plan'" in api
    assert "'pending_plan_effective_at'" in api


def test_r2_join_notification_names_member():
    invite = read('app/services/family_circle_invite_service.py')
    assert "new_user.full_name" in invite
    assert "joined the circle" in invite
