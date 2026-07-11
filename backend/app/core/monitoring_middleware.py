# Monitoring Middleware — Automatically tracks API request latency and errors.
#
# Two recorders are fed in one pass:
#   1. `monitoring_service.record_request` (legacy, in-memory dashboard)
#   2. `latency_histograms.record`        (new, Redis-backed p50/p95/p99)
#
# Path normalization: we prefer the FastAPI *route template*
# (`request.scope['route'].path`, e.g. `/api/users/{user_id}`) so that
# cardinality stays bounded. Falls back to a `__unrouted__` bucket
# for 404s so route-typo storms are visible without polluting real
# endpoint stats.
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


def _route_template(request: Request) -> str:
    """Best-effort: FastAPI route pattern, raw path, or `__unrouted__`."""
    route = request.scope.get("route")
    if route is not None:
        tpl = getattr(route, "path", None)
        if tpl:
            return tpl
    # Hit a 404 before the route was resolved — bucket it so we still
    # see traffic but it doesn't merge into a real endpoint.
    path = request.url.path or "__unrouted__"
    # An unrouted path that still starts with /api/ is almost always a
    # typo / probe — collapse all of them into one bucket.
    if not request.scope.get("route") and path.startswith("/api/"):
        return "__unrouted_api__"
    return path


class MonitoringMiddleware(BaseHTTPMiddleware):
    """Middleware to record API latency + error rates for every request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            # On unhandled, downstream error handlers will produce a 500.
            # Record it as such so the histograms reflect reality.
            status_code = 500
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            path = request.url.path or ""
            method = request.method or "GET"

            # Only track API paths — static assets / health-check noise
            # would skew percentiles and inflate Redis cardinality.
            if path.startswith("/api/"):
                template = _route_template(request)
                try:
                    from app.services.monitoring_service import record_request
                    record_request(method, template, status_code, duration_ms)
                except Exception:
                    pass
                try:
                    from app.services.latency_histograms import record as record_hist
                    record_hist(method, template, status_code, duration_ms)
                except Exception:
                    pass

        return response
