"""Request correlation and bounded, non-personal application request records."""
from datetime import datetime, timezone
import json
import logging
import re
import time
import uuid

from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, ProgrammingError, TimeoutError as PoolTimeoutError
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

# Only fixed labels may leave this classifier. Driver messages can contain
# credentials, hostnames and personal data, so never attach their text to logs.
CONNECTION_FAILURE_REASONS = tuple((re.compile(pattern), label) for pattern, label in (
    (r"compute(?: time)? quota (?:has been )?exceeded|exceeded (?:the )?compute(?: time)? quota", "compute_quota_exceeded"),
    (r"(?:quota|allowance|usage limit|compute time limit|monthly limit|free tier limit) (?:has been )?(?:exceeded|reached)|exceeded (?:the )?quota", "provider_quota_exceeded"),
    (r'endpoint (?:["\'][^"\'\r\n]{1,128}["\'] |[a-z0-9-]{1,128} )?(?:is|has been) (?:currently )?disabled', "endpoint_disabled"),
    (r"endpoint (?:is|has been) suspended", "endpoint_suspended"),
    (r"project (?:is|has been) (?:suspended|disabled)", "project_unavailable"),
    (r"the endpoint id is not specified|endpoint id is not specified|missing endpoint id", "endpoint_id_missing"),
    (r'endpoint (?:["\'][^"\'\r\n]{1,128}["\'] |[a-z0-9-]{1,128} )?(?:does not exist|not found)|the specified endpoint does not exist', "endpoint_missing"),
    (r"project not found|project does not exist", "project_missing"),
    (r"control plane request failed", "provider_control_plane_unavailable"),
    (r"no password supplied|password is required|no password was provided", "password_missing"),
    (r'role ["\'][^"\'\r\n]{1,256}["\'] does not exist|no postgresql user name specified', "role_missing"),
    (r"password authentication failed|authentication failed", "authentication_failed"),
    (r"no pg_hba.conf entry|ip address is not allowed|ip address is not in the allowlist", "connection_access_denied"),
    (r"request could not be authorized due to an internal error", "provider_authorization_failed"),
    (r"unsupported startup parameter", "startup_parameter_unsupported"),
    (r"invalid connection option|invalid dsn|invalid uri query parameter|invalid uri scheme|invalid sslmode value|invalid channel_binding value|invalid connection string", "connection_options_invalid"),
    (r'missing "=" after|invalid (?:integer )?value ["\'][^"\'\r\n]{1,256}["\'] for connection option', "connection_options_invalid"),
    (r'database "[^"\r\n]{1,256}" does not exist', "database_missing"),
    (r"could not translate host name|could not resolve host|name or service not known|temporary failure in name resolution", "dns_resolution_failed"),
    (r"query_wait_timeout|server_login_retry|pgbouncer cannot connect|pooler is not available", "pooler_unavailable"),
    (r"terminating connection due to administrator command", "server_terminated_connection"),
    (r"terminating connection due to idle-in-transaction timeout", "idle_transaction_timeout"),
    (r"connection refused", "connection_refused"),
    (r"connection timed out|connection timeout expired|timeout expired", "connection_timeout"),
    (r"certificate verify failed|certificate verification failed|ssl error: certificate|server certificate.*does not match host name|root certificate file.*does not exist", "tls_verification_failed"),
    (r"ssl connection has been closed unexpectedly|ssl syscall error|tls handshake failed|ssl handshake failed|connection is insecure", "tls_connection_failed"),
    (r"server closed the connection unexpectedly|server closed connection|connection reset by peer|connection is closed|connection is bad|unexpected eof", "connection_closed"),
    (r"network is unreachable|no route to host|cannot assign requested address|address family not supported", "network_unreachable"),
    (r"could not create socket|could not connect to server.*no such file or directory|connection to server on socket.*no such file or directory", "socket_unavailable"),
    (r"could not connect to server.*permission denied|connection to server.*permission denied", "socket_access_denied"),
    (r"couldn't connect to compute node", "compute_unavailable"),
    (r"remaining connection slots are reserved|too many connections|too many clients already", "connection_limit_exceeded"),
    (r"active endpoints limit exceeded|exceeded the limit of concurrently active endpoints", "endpoint_limit_exceeded"),
))

# Fallback diagnostics report only these source-code enums, never class names or
# matched input. Indicators are clues, not a guessed cause for unknown errors.
DRIVER_ERROR_KINDS = {
    "OperationalError": "operational", "ConnectionTimeout": "connection_timeout",
    "InterfaceError": "interface", "ProgrammingError": "programming",
    "InternalError": "internal", "DatabaseError": "database", "Error": "driver",
    "OSError": "os", "ConnectionError": "connection", "TimeoutError": "timeout",
    "ConnectionRefusedError": "refused", "ConnectionResetError": "reset",
}
CONNECTION_ERROR_INDICATORS = tuple((re.compile(pattern), label) for pattern, label in (
    (r"\bauth(?:entication|orization)?\b", "auth"), (r"\bpassword\b", "password"),
    (r"\brole\b|\buser\b", "role"), (r"\bendpoint\b|\bsni\b", "endpoint"),
    (r"\bcompute\b", "compute"), (r"\bquota\b|\blimit\b|\ballowance\b", "quota"),
    (r"\bproject\b|\bcontrol plane\b", "provider_project"),
    (r"\bpool(?:er)?\b|\bpgbouncer\b", "pool"),
    (r"\bssl(?:mode)?\b|\btls\b|\bcertificate\b|\bchannel_binding\b", "tls"),
    (r"\btimeout\b|\btimed out\b", "timeout"),
    (r"\bdns\b|\bresolve\b|\bresolution\b|\btranslate host\b", "dns"),
    (r"\bnetwork\b|\bsocket\b|\baddress\b", "network"),
    (r"\bconnection\b|\bconnect\b", "connection"),
    (r"\bclosed\b|\bclosing\b|\breset\b|\beof\b", "closed"),
    (r"\brefused\b", "refused"), (r"\bpermission\b|\bdenied\b", "permission"),
    (r"\boptions?\b|\bparameters?\b|\bdsn\b|\buri\b", "connection_options"),
    (r"\bsuspended\b|\bdisabled\b", "disabled"),
))
PG_CONNECTION_STATUSES = {
    0: "ok", 1: "bad", 2: "started", 3: "made", 4: "awaiting_response",
    5: "auth_ok", 6: "setenv", 7: "ssl_startup", 8: "needed",
    9: "check_writable", 10: "consume", 11: "gss_startup", 12: "check_target",
    13: "check_standby", 14: "allocated", 15: "authenticating",
}


def safe_attribute(value: object, name: str):
    """Optional driver properties may be unavailable on failed connections."""
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def connection_metadata(driver_error: Exception) -> dict[str, str | bool]:
    """Read only non-secret libpq state, including psycopg's FinishedPGconn."""
    connection = safe_attribute(driver_error, "pgconn")
    if connection is None:
        return {"connection_metadata": "absent"}
    status = safe_attribute(connection, "status")
    details: dict[str, str | bool] = {
        "connection_metadata": "available",
        "connection_status": PG_CONNECTION_STATUSES.get(status, "unknown")
        if isinstance(status, int) and not isinstance(status, bool) else "unknown",
    }
    for name in ("needs_password", "used_password", "ssl_in_use"):
        value = safe_attribute(connection, name)
        if isinstance(value, bool):
            details["connection_" + name] = value
    return details


def connection_failure_details(driver_error: Exception) -> dict[str, str | bool | list[str]]:
    """Inspect a bounded message; emit only fixed reasons, kinds and indicators."""
    details: dict[str, str | bool | list[str]] = {
        "driver_error_kind": DRIVER_ERROR_KINDS.get(type(driver_error).__name__, "other"),
        **connection_metadata(driver_error),
    }
    try:
        message = str(driver_error)[:8192].lower()
    except Exception:
        details["driver_message_state"] = "unrenderable"
        return details
    reason = next((label for pattern, label in CONNECTION_FAILURE_REASONS if pattern.search(message)), None)
    if reason:
        details["error_reason"] = reason
    else:
        details["driver_message_state"] = "unrecognized" if message.strip() else "empty"
        indicators = [label for pattern, label in CONNECTION_ERROR_INDICATORS if pattern.search(message)]
        if indicators:
            details["error_indicators"] = indicators
    return details


def failure_details(error: Exception) -> dict[str, str | bool | list[str]]:
    """Classify failures without logging exceptions, SQL or driver messages."""
    category = "application"
    for exception_type, label in (
        (OperationalError, "database_operational"),
        (ProgrammingError, "database_programming"),
        (IntegrityError, "database_integrity"),
        (PoolTimeoutError, "database_pool_timeout"),
        (DBAPIError, "database_other"),
    ):
        if isinstance(error, exception_type):
            category = label
            break
    details: dict[str, str | bool | list[str]] = {"error_category": category}
    if isinstance(error, DBAPIError):
        for code in (safe_attribute(error.orig, "sqlstate"), safe_attribute(safe_attribute(error.orig, "diag"), "sqlstate")):
            if isinstance(code, str) and re.fullmatch(r"[A-Z0-9]{5}", code):
                details["sqlstate"] = code
                break
    if isinstance(error, OperationalError):
        details.update(connection_failure_details(error.orig))
    return details


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
        error_details = None

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
        except Exception as error:
            error_kind = "server_error"
            error_details = failure_details(error)
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
            failed = bool(error_kind or status_code >= 500)
            if failed:
                record.update(error_details or {"error_category": "application"})
                record["diagnostics_version"] = "2"
            logger.log(logging.ERROR if failed else logging.INFO,
                       json.dumps(record, ensure_ascii=True, separators=(",", ":")))
