"""Failure records classify database errors without exposing request or SQL data."""
import asyncio
import json
import logging
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, ProgrammingError, TimeoutError
from starlette.responses import JSONResponse

from app.request_diagnostics import RequestDiagnostics, logger


PRIVATE = "synthetic-private-token participant@example.test postgresql://user:secret@host/db"


class SyntheticDriverError(Exception):
    def __init__(self, code, message=PRIVATE):
        super().__init__(message)
        self.sqlstate = code


def observe(monkeypatch, *, error=None, status=200, streaming=False):
    records = []
    messages = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    monkeypatch.setattr(logger, "handlers", [Capture()])
    # Earlier migration tests call Alembic's fileConfig(), which disables all
    # existing application loggers in this pytest process. Restore the API's
    # normal logging state only for this observation; monkeypatch restores it.
    monkeypatch.setattr(logger, "disabled", False)
    monkeypatch.setattr(logger, "level", logging.INFO)

    async def application(scope, receive, send):
        if streaming:
            await send({"type": "http.response.start", "status": 200, "headers": []})
        if error:
            raise error
        await JSONResponse({"ok": status < 500}, status_code=status)(scope, receive, send)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "method": "GET", "path": "/" + PRIVATE,
             "query_string": PRIVATE.encode(), "headers": [(b"x-request-id", PRIVATE.encode())],
             "route": SimpleNamespace(path="/directions/{direction_id}")}
    interrupted = None
    try:
        asyncio.run(RequestDiagnostics(application)(scope, receive, send))
    except RuntimeError as caught:
        interrupted = caught
    assert len(records) == 1
    record = records[0]
    assert record.exc_info is None and record.stack_info is None
    data = json.loads(record.getMessage())
    assert PRIVATE not in record.getMessage()
    assert data["route"] == "/directions/{direction_id}"
    assert UUID(data["request_id"]).version == 4
    header = dict(messages[0]["headers"])
    assert header[b"x-request-id"].decode() == data["request_id"]
    assert header[b"cache-control"] == b"no-store"
    return record, data, messages, interrupted


@pytest.mark.parametrize("exception_type,category,sqlstate", [
    (OperationalError, "database_operational", "08006"),
    (ProgrammingError, "database_programming", "42P01"),
    (IntegrityError, "database_integrity", "23505"),
    (DBAPIError, "database_other", "XX000"),
])
def test_database_failures_log_safe_categories_and_sqlstate(monkeypatch, exception_type, category, sqlstate):
    error = exception_type("SELECT " + PRIVATE, {"password": PRIVATE}, SyntheticDriverError(sqlstate))
    record, data, messages, interrupted = observe(monkeypatch, error=error)
    assert record.levelno == logging.ERROR
    assert data["status_code"] == 500 and data["error_kind"] == "server_error"
    assert data["diagnostics_version"] == "2"
    assert data["error_category"] == category and data["sqlstate"] == sqlstate
    assert interrupted is None
    body = json.loads(messages[1]["body"])
    assert body["request_id"] == data["request_id"]
    assert body["detail"] == "Не удалось выполнить запрос. Повторите попытку."
    assert "error_category" not in body and "sqlstate" not in body
    assert PRIVATE not in str(messages)


@pytest.mark.parametrize("code", [None, "42p01", "42P01\n", "42P01 extra", PRIVATE, 12345, b"42P01"])
def test_invalid_sqlstate_is_not_logged(monkeypatch, code):
    error = OperationalError(PRIVATE, {"token": PRIVATE}, SyntheticDriverError(code))
    _, data, _, _ = observe(monkeypatch, error=error)
    assert data["error_category"] == "database_operational"
    assert "sqlstate" not in data


@pytest.mark.parametrize("error,category", [
    (TimeoutError(PRIVATE), "database_pool_timeout"),
    (ValueError(PRIVATE), "application"),
])
def test_pool_and_application_failures_are_error_level(monkeypatch, error, category):
    record, data, _, _ = observe(monkeypatch, error=error)
    assert record.levelno == logging.ERROR
    assert data["error_category"] == category
    assert "sqlstate" not in data


def test_explicit_server_error_response_is_error_level(monkeypatch):
    record, data, _, _ = observe(monkeypatch, status=503)
    assert record.levelno == logging.ERROR
    assert data["status_code"] == 503 and data["error_category"] == "application"
    assert data["diagnostics_version"] == "2"
    assert "error_kind" not in data


def test_success_remains_info_without_failure_fields(monkeypatch):
    record, data, _, _ = observe(monkeypatch)
    assert record.levelno == logging.INFO and data["status_code"] == 200
    assert not {"error_kind", "error_category", "sqlstate", "diagnostics_version"} & data.keys()


def test_streaming_error_records_cause_without_leaking_original_exception(monkeypatch):
    error = OperationalError(PRIVATE, {"token": PRIVATE}, SyntheticDriverError("08006"))
    record, data, _, interrupted = observe(monkeypatch, error=error, streaming=True)
    assert record.levelno == logging.ERROR
    assert data["status_code"] == 200 and data["error_category"] == "database_operational"
    assert data["sqlstate"] == "08006"
    assert str(interrupted) == "Response interrupted; use the request ID"
    assert interrupted.__suppress_context__


@pytest.mark.parametrize("message,reason", [
    ("Your project has exceeded the compute time quota. Upgrade your plan.", "compute_quota_exceeded"),
    ("Compute quota exceeded", "compute_quota_exceeded"),
    ("The endpoint is disabled", "endpoint_disabled"),
    ("The endpoint has been disabled", "endpoint_disabled"),
    ('password authentication failed for user "synthetic-user"', "authentication_failed"),
    ('database "synthetic-db" does not exist', "database_missing"),
    ('could not translate host name "synthetic-host" to address: Name or service not known', "dns_resolution_failed"),
    ("Temporary failure in name resolution", "dns_resolution_failed"),
    ("connection to server failed: Connection refused", "connection_refused"),
    ("connection to server failed: timeout expired", "connection_timeout"),
    ("connection timed out", "connection_timeout"),
    ("SSL error: certificate verify failed", "tls_verification_failed"),
    ("SSL connection has been closed unexpectedly", "tls_connection_failed"),
    ("Couldn't connect to compute node", "compute_unavailable"),
    ("remaining connection slots are reserved for roles with the SUPERUSER attribute", "connection_limit_exceeded"),
    ("active endpoints limit exceeded", "endpoint_limit_exceeded"),
])
def test_known_connection_failures_log_only_a_static_reason(monkeypatch, message, reason):
    driver = SyntheticDriverError(None, message + "\n" + PRIVATE)
    error = OperationalError("SELECT " + PRIVATE, {"password": PRIVATE}, driver)
    record, data, messages, _ = observe(monkeypatch, error=error)
    assert record.levelno == logging.ERROR
    assert data["error_category"] == "database_operational"
    assert data["error_reason"] == reason and "sqlstate" not in data
    assert message not in record.getMessage()
    body = json.loads(messages[1]["body"])
    assert "error_reason" not in body
    assert PRIVATE not in str(messages)


@pytest.mark.parametrize("message", [
    PRIVATE, "Unrecognized driver failure", "The compute quota is not exceeded",
    'relation "synthetic-db" does not exist', "database is unavailable",
])
def test_unknown_driver_messages_do_not_guess_a_connection_reason(monkeypatch, message):
    error = OperationalError("SELECT 'password authentication failed' " + PRIVATE,
                             {"password": PRIVATE}, SyntheticDriverError(None, message))
    _, data, _, _ = observe(monkeypatch, error=error)
    assert "error_reason" not in data


def test_non_connection_errors_do_not_infer_reasons_from_their_message(monkeypatch):
    error = ProgrammingError(PRIVATE, {"token": PRIVATE},
                             SyntheticDriverError("42P01", "connection refused " + PRIVATE))
    _, data, _, _ = observe(monkeypatch, error=error)
    assert data["error_category"] == "database_programming"
    assert "error_reason" not in data


def test_unrenderable_driver_message_does_not_break_safe_diagnostics(monkeypatch):
    class UnrenderableDriverError(Exception):
        def __str__(self):
            raise ValueError(PRIVATE)

    error = OperationalError(PRIVATE, {"token": PRIVATE}, UnrenderableDriverError())
    _, data, _, _ = observe(monkeypatch, error=error)
    assert data["error_category"] == "database_operational"
    assert "error_reason" not in data
    assert data["driver_message_state"] == "unrenderable"


@pytest.mark.parametrize("message,reason", [
    ("fe_sendauth: no password supplied", "password_missing"),
    ('FATAL: role "synthetic-user" does not exist', "role_missing"),
    ("invalid connection option: synthetic-option", "connection_options_invalid"),
    ("invalid sslmode value: synthetic-value", "connection_options_invalid"),
    ('invalid integer value "synthetic-value" for connection option "port"', "connection_options_invalid"),
    ('missing "=" after "synthetic-option" in connection info string', "connection_options_invalid"),
    ("The endpoint ID is not specified. Upgrade libpq for SNI support", "endpoint_id_missing"),
    ("The specified endpoint does not exist", "endpoint_missing"),
    ("endpoint ep-synthetic-example is disabled", "endpoint_disabled"),
    ('endpoint "ep-synthetic-example" is disabled', "endpoint_disabled"),
    ("This endpoint is currently disabled", "endpoint_disabled"),
    ("endpoint ep-synthetic-example not found", "endpoint_missing"),
    ('endpoint "ep-synthetic-example" not found', "endpoint_missing"),
    ("project not found", "project_missing"),
    ("control plane request failed", "provider_control_plane_unavailable"),
    ("endpoint is suspended", "endpoint_suspended"),
    ("project has been disabled", "project_unavailable"),
    ("Monthly limit exceeded", "provider_quota_exceeded"),
    ("quota reached", "provider_quota_exceeded"),
    ("sorry, too many clients already", "connection_limit_exceeded"),
    ("unsupported startup parameter in options: synthetic", "startup_parameter_unsupported"),
    ("query_wait_timeout SSL connection has been closed unexpectedly", "pooler_unavailable"),
    ("server_login_retry", "pooler_unavailable"),
    ("The request could not be authorized due to an internal error", "provider_authorization_failed"),
    ('no pg_hba.conf entry for host "synthetic-host"', "connection_access_denied"),
    ("terminating connection due to administrator command", "server_terminated_connection"),
    ("terminating connection due to idle-in-transaction timeout", "idle_transaction_timeout"),
    ("server closed the connection unexpectedly", "connection_closed"),
    ("connection reset by peer", "connection_closed"),
    ("network is unreachable", "network_unreachable"),
    ("could not create socket", "socket_unavailable"),
    ('connection to server on socket "/synthetic/path" failed: No such file or directory', "socket_unavailable"),
    ('connection to server on socket "/synthetic/path" failed: Permission denied', "socket_access_denied"),
])
def test_libpq_and_neon_variants_use_fixed_reasons_only(monkeypatch, message, reason):
    error = OperationalError(PRIVATE, {"token": PRIVATE}, SyntheticDriverError(None, message + "\n" + PRIVATE))
    record, data, messages, _ = observe(monkeypatch, error=error)
    assert data["error_reason"] == reason
    assert data["driver_error_kind"] == "other"
    assert message not in record.getMessage() and PRIVATE not in str(messages)
    assert "error_reason" not in json.loads(messages[1]["body"])


def test_unrecognized_connection_error_exposes_only_fixed_keyword_indicators(monkeypatch):
    message = "Unrecognized failure involving password, endpoint, compute, quota, pooler, SSL, timeout, DNS, network, closed socket, refused permission and options"
    error = OperationalError(PRIVATE, {"token": PRIVATE}, SyntheticDriverError(None, message + " " + PRIVATE))
    record, data, _, _ = observe(monkeypatch, error=error)
    assert "error_reason" not in data
    assert data["driver_message_state"] == "unrecognized"
    assert data["driver_error_kind"] == "other"
    assert set(data["error_indicators"]) == {
        "password", "endpoint", "compute", "quota", "pool", "tls", "timeout", "dns",
        "network", "closed", "refused", "permission",
        "connection_options", "role",
    }
    assert message not in record.getMessage()


def test_empty_driver_message_is_distinguished_from_unknown_text(monkeypatch):
    error = OperationalError(PRIVATE, {}, SyntheticDriverError(None, ""))
    _, data, _, _ = observe(monkeypatch, error=error)
    assert data["driver_message_state"] == "empty"
    assert "error_reason" not in data and "error_indicators" not in data


@pytest.mark.parametrize("name,expected", [
    ("OperationalError", "operational"), ("ConnectionTimeout", "connection_timeout"),
    ("InterfaceError", "interface"), ("ProgrammingError", "programming"),
    ("SyntheticSecretClass", "other"),
])
def test_driver_class_name_is_never_logged_outside_the_static_enum(monkeypatch, name, expected):
    driver_type = type(name, (Exception,), {})
    error = OperationalError(PRIVATE, {}, driver_type(PRIVATE))
    record, data, _, _ = observe(monkeypatch, error=error)
    assert data["driver_error_kind"] == expected
    assert name not in record.getMessage()


@pytest.mark.parametrize("primary", [None, "invalid", "42p01"])
def test_sqlstate_can_use_validated_diagnostic_fallback(monkeypatch, primary):
    driver = SyntheticDriverError(primary)
    driver.diag = SimpleNamespace(sqlstate="08006", message_primary=PRIVATE)
    error = OperationalError(PRIVATE, {"token": PRIVATE}, driver)
    _, data, _, _ = observe(monkeypatch, error=error)
    assert data["sqlstate"] == "08006"


@pytest.mark.parametrize("code", [PRIVATE, "42p01", "42P01\n", 12345, None])
def test_diagnostic_sqlstate_fallback_is_strictly_validated(monkeypatch, code):
    driver = SyntheticDriverError(None)
    driver.diag = SimpleNamespace(sqlstate=code)
    _, data, _, _ = observe(monkeypatch, error=OperationalError(PRIVATE, {}, driver))
    assert "sqlstate" not in data


def test_libpq_metadata_reads_only_whitelisted_non_secret_properties(monkeypatch):
    accessed = []
    values = {"status": 1, "needs_password": True, "used_password": False, "ssl_in_use": True}

    class RestrictedPGConn:
        def __getattribute__(self, name):
            accessed.append(name)
            if name in values:
                return values[name]
            raise AssertionError("Attempt to read private connection metadata: " + PRIVATE)

    driver = SyntheticDriverError(None, "Unrecognized connection failure " + PRIVATE)
    driver.pgconn = RestrictedPGConn()
    _, data, messages, _ = observe(monkeypatch, error=OperationalError(PRIVATE, {}, driver))
    assert accessed == ["status", "needs_password", "used_password", "ssl_in_use"]
    assert data["connection_metadata"] == "available" and data["connection_status"] == "bad"
    assert data["connection_needs_password"] is True
    assert data["connection_used_password"] is False
    assert data["connection_ssl_in_use"] is True
    assert "connection_status" not in json.loads(messages[1]["body"])


@pytest.mark.parametrize("status,flag", [(PRIVATE, PRIVATE), (True, 1), (99, "true"), (None, None)])
def test_libpq_metadata_rejects_non_enum_status_and_non_boolean_flags(monkeypatch, status, flag):
    driver = SyntheticDriverError(None)
    driver.pgconn = SimpleNamespace(status=status, needs_password=flag, used_password=flag, ssl_in_use=flag)
    _, data, _, _ = observe(monkeypatch, error=OperationalError(PRIVATE, {}, driver))
    assert data["connection_status"] == "unknown"
    assert not {"connection_needs_password", "connection_used_password", "connection_ssl_in_use"} & data.keys()


def test_failed_optional_driver_properties_do_not_break_error_response(monkeypatch):
    class UnavailableMetadataError(Exception):
        @property
        def sqlstate(self):
            raise ValueError(PRIVATE)

        @property
        def diag(self):
            raise ValueError(PRIVATE)

        @property
        def pgconn(self):
            raise ValueError(PRIVATE)

    _, data, messages, _ = observe(monkeypatch, error=OperationalError(PRIVATE, {}, UnavailableMetadataError(PRIVATE)))
    assert data["status_code"] == 500 and data["connection_metadata"] == "absent"
    assert "sqlstate" not in data
    assert json.loads(messages[1]["body"])["request_id"] == data["request_id"]
