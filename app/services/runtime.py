from __future__ import annotations

import contextvars
import hashlib
import re
import threading
import time
from collections import defaultdict, deque
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="unknown")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def current_request_id() -> str:
    return request_id_var.get()


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        current = now if now is not None else time.monotonic()
        cutoff = current - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, round(events[0] + self.window_seconds - current))
                return False, retry_after
            events.append(current)
            return True, 0


class RuntimeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, request_limit_per_minute: int, secure_environment: bool = False) -> None:
        super().__init__(app)
        self.limiter = SlidingWindowRateLimiter(request_limit_per_minute)
        self.secure_environment = secure_environment

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_id = request.headers.get("X-Request-ID", "")
        request_id = supplied_id if REQUEST_ID_PATTERN.fullmatch(supplied_id) else str(uuid4())
        token = request_id_var.set(request_id)
        try:
            if request.url.path.startswith("/api/") and request.url.path not in {"/api/health", "/api/config"}:
                authorization = request.headers.get("Authorization", "anonymous")
                key = hashlib.sha256(authorization.encode()).hexdigest()
                allowed, retry_after = self.limiter.allow(key)
                if not allowed:
                    response: Response = JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded", "request_id": request_id},
                        headers={"Retry-After": str(retry_after)},
                    )
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
            if self.secure_environment:
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            if request.url.path.startswith("/api/"):
                response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            request_id_var.reset(token)
