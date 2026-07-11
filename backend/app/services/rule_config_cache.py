# Rule Config In-Memory Cache with TTL
from datetime import datetime, timezone, timedelta


class RuleConfigCache:
    def __init__(self, ttl_seconds=30):
        self.ttl = timedelta(seconds=ttl_seconds)
        self._cache = {}
        self._last_refresh = {}

    def is_expired(self, rule_name):
        if rule_name not in self._last_refresh:
            return True
        return datetime.now(timezone.utc) - self._last_refresh[rule_name] > self.ttl

    def get(self, rule_name):
        if self.is_expired(rule_name):
            return None
        return self._cache.get(rule_name)

    def set(self, rule_name, value):
        self._cache[rule_name] = value
        self._last_refresh[rule_name] = datetime.now(timezone.utc)

    def invalidate(self, rule_name: str | None = None):
        """Invalidate a single rule or all cached entries."""
        if rule_name:
            self._cache.pop(rule_name, None)
            self._last_refresh.pop(rule_name, None)
        else:
            self._cache.clear()
            self._last_refresh.clear()


rule_config_cache = RuleConfigCache()
