"""The local pilot must reject cloud URLs and inherited deployment settings."""
import importlib.util
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[3] / "scripts/verification/postgres_load.py"
spec = importlib.util.spec_from_file_location("postgres_pilot", SOURCE)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


@pytest.mark.parametrize("value", [
    "postgresql://user:synthetic@127.0.0.1:55432/dc_pilot_load_unit",
    "postgres://user:synthetic@[::1]:55432/danaconnect_load_unit?sslmode=disable&connect_timeout=5",
])
def test_local_pilot_accepts_explicit_loopback_empty_database_name(value):
    assert pilot.validate_database_url(value).startswith("postgresql+psycopg://")


@pytest.mark.parametrize("value", [
    "postgresql://user:synthetic@cloud.example.test:5432/dc_pilot_load_unit",
    "postgresql://user:synthetic@localhost:55432/dc_pilot_load_unit",
    "postgresql://user:synthetic@127.0.0.1:55432/production",
    "postgresql://user:synthetic@127.0.0.1/dc_pilot_load_unit",
    "sqlite:///dc_pilot_load_unit.db",
    "postgresql://user:synthetic@127.0.0.1:55432/dc_pilot_load_unit?host=cloud.example.test",
    "postgresql://user:synthetic@127.0.0.1:55432/dc_pilot_load_unit?service=production",
    "postgresql://user:synthetic@127.0.0.1:55432/dc_pilot_load_unit?options=-csearch_path=production",
    "postgresql://user:synthetic@127.0.0.1:55432/dc_pilot_load_unit?sslmode=disable&sslmode=require",
    "postgresql://user:synthetic@127.0.0.1:55432/dc_pilot_load_unit?connect_timeout=0",
    "postgresql://user:synthetic@127.0.0.1:55432/dc_pilot_load_unit?connect_timeout=bad",
    "postgresql://user:synthetic@127.0.0.1:55432/dc_pilot_load_unit#production",
])
def test_local_pilot_rejects_remote_ambiguous_or_overridden_targets(value):
    with pytest.raises(pilot.PilotError):
        pilot.validate_database_url(value)


def test_local_pilot_environment_drops_deployment_credentials(monkeypatch):
    for key in ["DATABASE_URL", "SMTP_PASSWORD", "AUTH_SECRET", "GOOGLE_CLIENT_SECRET",
                "VERCEL_OIDC_TOKEN", "BLOB_READ_WRITE_TOKEN", "RESEND_API_KEY"]:
        monkeypatch.setenv(key, "SYNTHETIC-INHERITED-SECRET")
    safe_url = "postgresql+psycopg://user:synthetic@127.0.0.1:55432/dc_pilot_load_unit"
    env = pilot.clean_environment(safe_url)
    assert env["DATABASE_URL"] == safe_url
    assert env["AUTH_SECRET"] == pilot.AUTH_SECRET
    assert all(value != "SYNTHETIC-INHERITED-SECRET" for value in env.values())
    assert env["EMAIL_PROVIDER"] == env["STORAGE_PROVIDER"] == "none"
    assert env["AI_ENABLED"] == env["AUTH_DEBUG_CODE"] == env["DEMO_MODE"] == "false"


def test_local_pilot_statistics_document_nearest_rank():
    assert pilot.percentile([3, 1, 2, 20], 50) == 2
    assert pilot.percentile([3, 1, 2, 20], 95) == 20
    summary = pilot.summarize([
        {"latency_ms": 1, "status": 200}, {"latency_ms": 3, "status": 409},
        {"latency_ms": 20, "status": 500}, {"latency_ms": 2, "status": 0},
    ], 2)
    assert summary["statuses"] == {"200": 1, "409": 1, "500": 1, "0": 1}
    assert summary["transport_errors"] == summary["server_errors"] == 1
    assert summary["requests_per_second"] == 2
