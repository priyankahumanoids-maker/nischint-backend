"""Shared OTP quotas. No client creation, settings or network work at import.

The general API limiter retains its availability fallback. OTP quotas instead
require the existing shared Redis service; process memory is not distributed.
"""
from app.core.auth_foundation_policy import keyed_identity


class QuotaUnavailable(Exception):
    pass


# One atomic operation, including counters that exceed their quota. Repeated
# denied requests cannot extend the fixed window indefinitely.
QUOTA_SCRIPT = """
local retry = 0
for i, key in ipairs(KEYS) do
    local count = redis.call('INCR', key)
    if count == 1 then redis.call('EXPIRE', key, tonumber(ARGV[1])) end
    local ttl = redis.call('TTL', key)
    if ttl < 0 then
        redis.call('EXPIRE', key, tonumber(ARGV[1]))
        ttl = tonumber(ARGV[1])
    end
    if count > tonumber(ARGV[i + 1]) then retry = math.max(retry, ttl, 1) end
end
return retry
"""


def quota_spec(*, identity, ip, purpose, operation, key, include_peer=True):
    if operation not in {"issue", "verify"} or not purpose or not identity or not ip:
        raise ValueError("An explicit OTP identity, peer IP, purpose and operation are required")
    # Phone/account-wide limits survive purpose switching. The IP limit is
    # shared across issue/verify so changing identities cannot evade it.
    digest = keyed_identity(key, "otp-quota-identity", identity)
    peer = keyed_identity(key, "otp-quota-peer", ip)
    scoped = keyed_identity(key, "otp-quota-purpose", f"{identity}:{purpose}:{operation}")
    keys = [f"auth:otp:ip:{peer}", f"auth:otp:{operation}:{digest}", f"auth:otp:purpose:{scoped}"]
    limits = [60, 5 if operation == "issue" else 15, 3 if operation == "issue" else 10]
    if not include_peer:
        keys, limits = keys[1:], limits[1:]
    return keys, [300, *limits]


def check_quota(client, **kwargs):
    keys, args = quota_spec(**kwargs)
    if client is None:
        raise QuotaUnavailable("Shared OTP quota service unavailable")
    try:
        result = int(client.eval(QUOTA_SCRIPT, len(keys), *keys, *args))
    except Exception:
        raise QuotaUnavailable("Shared OTP quota service unavailable") from None
    if result < 0:
        raise QuotaUnavailable("Invalid OTP quota result")
    return result
