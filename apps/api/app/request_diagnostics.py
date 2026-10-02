"""Request correlation and bounded, non-personal application request records."""
from datetime import datetime, timezone
import json
import logging
import time
import uuid

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


logger = logging.getLogger("danaconnect.requests")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


class RequestDiagnostics:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid.uuid4())  # Never trust a caller-provided correlation ID.
        scope.setdefault("state", {})["request_id"] = request_id
        started_at = time.perf_counter()
        response_started = False
        status_code = 500
        error_kind = None

        async def annotated_send(message: Message):
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_started = True
                headers = [(key, value) for key, value in message.get("headers", [])
                           if key.lower() not in {b"x-request-id", b"cache-control", b"x-content-type-options"}]
                headers.extend([(b"x-request-id", request_id.encode("ascii")),
                                (b"cache-control", b"no-store"),
                                (b"x-content-type-options", b"nosniff")])
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, annotated_send)
        except Exception:
            error_kind = "server_error"
            if response_started:
                # A streaming response cannot be replaced after its headers.
                # Do not expose the original exception or its chained values.
                raise RuntimeError("Response interrupted; use the request ID") from None
            await JSONResponse(status_code=500, content={
                "detail": "Не удалось выполнить запрос. Повторите попытку.",
                "request_id": request_id,
            })(scope, receive, annotated_send)
        finally:
            # Only route metadata supplied by the router is used, never the URL.
            route = getattr(scope.get("route"), "path", None)
            template = route if isinstance(route, str) and len(route) <= 250 else "__unmatched__"
            record = {
                "event": "http_request", "observed_at": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
                "method": scope.get("method") if scope.get("method") in METHODS else "OTHER",
                "route": template, "status_code": status_code,
                "duration_ms": round(max(0, time.perf_counter() - started_at) * 1000, 2),
            }
            if error_kind:
                record["error_kind"] = error_kind
            logger.info(json.dumps(record, ensure_ascii=True, separators=(",", ":")))
