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
    assert "error_kind" not in data


def test_success_remains_info_without_failure_fields(monkeypatch):
    record, data, _, _ = observe(monkeypatch)
    assert record.levelno == logging.INFO and data["status_code"] == 200
    assert not {"error_kind", "error_category", "sqlstate"} & data.keys()


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
