from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.config import Settings


POOLER = "postgresql://operator:synthetic%40pass@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
LEGACY = "postgresql://operator:synthetic@legacy.test/previous?sslmode=require"


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "deploy"))
    import migrate_external
    return migrate_external


@pytest.mark.parametrize("legacy", [None, LEGACY])
def test_admin_operator_uses_same_pooler_and_certificate_as_api(operator, legacy):
    pooler = POOLER + "?sslmode=require&connect_timeout=10"
    values = {"SUPABASE_DATABASE_URL": pooler}
    if legacy:
        values["DATABASE_URL"] = legacy
    env = operator.private_environment(values, [])
    target = make_url(env["DATABASE_URL"])
    runtime = Settings(_env_file=None, supabase_database_url=pooler)
    assert target == make_url(runtime.database_url) == make_url(env["SUPABASE_DATABASE_URL"])
    assert target.query["sslmode"] == "verify-full"
    assert Path(target.query["sslrootcert"]).is_file()
    assert target.query["connect_timeout"] == "10"
    assert target.password == "synthetic@pass"


def test_operator_rejects_invalid_pooler_even_with_valid_legacy_url(operator):
    with pytest.raises(operator.OperatorError, match="managed PostgreSQL pooler"):
        operator.private_environment({"SUPABASE_DATABASE_URL": LEGACY, "DATABASE_URL": LEGACY}, [])


def test_operator_still_requires_tls_on_standalone_postgres(operator):
    env = operator.private_environment({"DATABASE_URL": LEGACY}, [])
    assert make_url(env["DATABASE_URL"]).host == "legacy.test"
    with pytest.raises(operator.OperatorError, match="TLS is required"):
        operator.private_environment({"DATABASE_URL": LEGACY.partition("?")[0]}, [])
