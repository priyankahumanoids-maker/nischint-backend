# Rule Config Loader — DB-backed with safe fallback to Settings defaults
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.rule_config import DeviceHealthRuleConfig
from app.services.rule_config_cache import rule_config_cache


@dataclass
class RuleConfig:
    """Unified rule config object used by the health scheduler."""
    rule_name: str
    enabled: bool
    threshold_json: dict
    cooldown_minutes: int
    severity: str


# Fallback defaults mirroring existing Settings values
_DEFAULTS = {
    "low_battery": RuleConfig(
        rule_name="low_battery",
        enabled=settings.rule_low_battery_enabled,
        threshold_json={
            "battery_percent": settings.low_battery_threshold_percent,
            "recovery_buffer": settings.low_battery_recovery_buffer_percent,
            "sustain_minutes": settings.low_battery_sustain_minutes,
        },
        cooldown_minutes=settings.low_battery_cooldown_minutes,
        severity="low",
    ),
    "signal_degradation": RuleConfig(
        rule_name="signal_degradation",
        enabled=settings.rule_signal_degradation_enabled,
        threshold_json={
            "signal_threshold": settings.signal_degradation_threshold_dbm,
            "recovery_buffer_dbm": settings.signal_degradation_recovery_buffer_dbm,
            "sustain_minutes": settings.signal_degradation_sustain_minutes,
        },
        cooldown_minutes=settings.signal_degradation_cooldown_minutes,
        severity="low",
    ),
    "reboot_anomaly": RuleConfig(
        rule_name="reboot_anomaly",
        enabled=settings.rule_reboot_anomaly_enabled,
        threshold_json={
            "gap_minutes": 3,
            "gap_count": settings.reboot_anomaly_max_reboots,
            "window_minutes": settings.reboot_anomaly_window_minutes,
        },
        cooldown_minutes=settings.reboot_anomaly_cooldown_minutes,
        severity="medium",
    ),
}


def _row_to_config(row) -> RuleConfig:
    return RuleConfig(
        rule_name=row.rule_name,
        enabled=row.enabled,
        threshold_json=row.threshold_json,
        cooldown_minutes=row.cooldown_minutes,
        severity=row.severity,
    )


async def get_rule_config(session: AsyncSession, rule_name: str) -> RuleConfig:
    """Load rule config: cache -> DB -> Settings fallback."""
    cached = rule_config_cache.get(rule_name)
    if cached is not None:
        return cached

    row = (await session.execute(
        select(DeviceHealthRuleConfig)
        .where(DeviceHealthRuleConfig.rule_name == rule_name)
    )).scalar_one_or_none()

    if row:
        cfg = _row_to_config(row)
        rule_config_cache.set(rule_name, cfg)
        return cfg

    fallback = _DEFAULTS.get(rule_name, RuleConfig(
        rule_name=rule_name, enabled=False, threshold_json={},
        cooldown_minutes=60, severity="low",
    ))
    rule_config_cache.set(rule_name, fallback)
    return fallback


async def get_all_rule_configs(session: AsyncSession) -> list[RuleConfig]:
    """Load all rule configs from DB."""
    rows = (await session.execute(
        select(DeviceHealthRuleConfig).order_by(DeviceHealthRuleConfig.rule_name)
    )).scalars().all()

    if rows:
        return [_row_to_config(r) for r in rows]
    return list(_DEFAULTS.values())
