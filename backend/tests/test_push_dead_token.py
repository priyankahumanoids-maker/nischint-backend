"""Tests for FCM dead-token recognition + purge.

The recognizer is pure and synchronous — easy to lock down. The purge
function reads/writes the DB so we mock it.
"""
from app.services.push_service import _is_dead_token_response


# ── Recognizer: known-dead responses ─────────────────────────────────
def test_unregistered_404_is_dead():
    body = '{"error":{"status":"NOT_FOUND","details":[{"errorCode":"UNREGISTERED"}]}}'
    assert _is_dead_token_response(404, body) is True


def test_not_found_404_is_dead():
    assert _is_dead_token_response(404, '{"error":{"status":"NOT_FOUND"}}') is True


def test_invalid_argument_400_is_dead():
    body = '{"error":{"status":"INVALID_ARGUMENT","details":[{"errorCode":"INVALID_ARGUMENT"}]}}'
    assert _is_dead_token_response(400, body) is True


def test_sender_id_mismatch_403_is_dead():
    body = '{"error":{"details":[{"errorCode":"SENDER_ID_MISMATCH"}]}}'
    assert _is_dead_token_response(403, body) is True


def test_legacy_registration_token_not_registered_is_dead():
    body = '{"error":"registration-token-not-registered"}'
    assert _is_dead_token_response(404, body) is True


# ── Recognizer: transient / unrelated failures must NOT purge ────────
def test_quota_exceeded_429_is_not_dead():
    body = '{"error":{"status":"RESOURCE_EXHAUSTED","details":[{"errorCode":"QUOTA_EXCEEDED"}]}}'
    assert _is_dead_token_response(429, body) is False


def test_internal_500_is_not_dead():
    assert _is_dead_token_response(500, '{"error":"internal"}') is False


def test_unavailable_503_is_not_dead():
    assert _is_dead_token_response(503, '{"error":{"status":"UNAVAILABLE"}}') is False


def test_unauthorized_401_is_not_dead():
    # Bad auth on OUR side — never purge customer tokens for this.
    assert _is_dead_token_response(401, "Unauthorized") is False


def test_empty_body_404_is_not_dead():
    # Without an errorCode payload we can't be sure — be safe, keep token.
    assert _is_dead_token_response(404, "") is False


def test_404_with_unknown_error_is_not_dead():
    # A 404 we don't recognize → don't risk a false-positive purge.
    body = '{"error":{"status":"DEADLINE_EXCEEDED"}}'
    assert _is_dead_token_response(404, body) is False
