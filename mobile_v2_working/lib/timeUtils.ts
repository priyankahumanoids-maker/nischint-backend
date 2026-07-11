// IST (India Standard Time) conversion utility
// All NISCHINT pilot users are in India — always display IST regardless of device timezone.
// Robust against backend timestamps missing the `Z` suffix (naive UTC) by auto-appending Z.

function _asUtcDate(ts: string): Date {
  // If the string already has a tz indicator (Z or +HH:MM / -HH:MM), parse as-is.
  // Otherwise treat it as UTC (Nischint backend stores everything in UTC).
  const hasTz = /(Z|[+-]\d{2}:?\d{2})$/i.test(ts);
  return hasTz ? new Date(ts) : new Date(ts + 'Z');
}

/**
 * Convert a UTC ISO timestamp string to IST and return a formatted time string (HH:MM AM/PM).
 */
export function toIST(ts: string | null | undefined): string {
  if (!ts) return '--';
  try {
    const d = _asUtcDate(ts);
    if (isNaN(d.getTime())) return '--';
    return d.toLocaleTimeString('en-IN', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: 'Asia/Kolkata',
    });
  } catch {
    return '--';
  }
}

/**
 * Convert a UTC ISO timestamp string to IST and return a formatted date+time string.
 */
export function toISTFull(ts: string | null | undefined): string {
  if (!ts) return '--';
  try {
    const d = _asUtcDate(ts);
    if (isNaN(d.getTime())) return '--';
    return d.toLocaleString('en-IN', {
      day: 'numeric',
      month: 'short',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: 'Asia/Kolkata',
    });
  } catch {
    return '--';
  }
}
