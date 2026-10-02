"""Backup operator contracts, using synthetic archives and no DB/provider sockets."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[3] / "deploy" / "postgres_backup.py"
SPEC = importlib.util.spec_from_file_location("isolated_postgres_backup", MODULE_PATH)
operator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = operator
SPEC.loader.exec_module(operator)

SOURCE_URL = "postgresql+psycopg://synthetic_user:synthetic%3Apassword%5Cvalue@source.example.test/live_database?sslmode=require"
SOURCE = operator.parse_connection(SOURCE_URL)
MAINTENANCE = operator.parse_connection("postgresql://local_operator:synthetic_local_password@127.0.0.1:55432/postgres?sslmode=disable")
NAME = "danaconnect_restore_probe"
SOURCE_LOCALE = {"encoding": 6, "provider": "b", "collate": "C.UTF-8", "ctype": "C.UTF-8", "locale": "C.UTF-8",
                 "icu_rules": None, "version": "1", "actual_version": "1"}
CONTROL_LOCALE = {"encoding": 6, "provider": "c", "collate": "C", "ctype": "C", "locale": None,
                  "icu_rules": None, "version": None, "actual_version": None}
SOURCE_ID = {"database_name": "live_database", "database_oid": "16384", "server_address": "192.0.2.5",
             "server_port": 5432, "server_version_num": 180006, "database_locale": SOURCE_LOCALE}
CONTROL_ID = {"database_name": "postgres", "database_oid": "5", "server_address": "127.0.0.1",
              "server_port": 55432, "server_version_num": 180006, "database_locale": CONTROL_LOCALE}


@pytest.fixture(autouse=True)
def private_synthetic_paths(monkeypatch):
    # Windows ACL behavior is tested separately. Contract tests use only pytest's
    # disposable files and never invoke a PostgreSQL/client/system executable.
    monkeypatch.setattr(operator, "restrict_path", lambda *args, **kwargs: None)
    monkeypatch.setattr(operator.subprocess, "run", lambda *args, **kwargs: pytest.fail("Unexpected external process in isolated backup tests"))


class FakeRunner:
    def __init__(self, *, exists=False, empty=True, alias=False, source_alias=False, wrong_oid=False, wrong_server=False,
                 fail_restore=False, target_locale_override=None, live_locale_override=None, control_version=None):
        self.calls = []
        self.exists, self.empty, self.alias = exists, empty, alias
        self.source_alias, self.wrong_oid, self.wrong_server, self.fail_restore = source_alias, wrong_oid, wrong_server, fail_restore
        self.target_locale_override, self.live_locale_override = target_locale_override, live_locale_override
        self.control_version = control_version

    def query(self, env, sql):
        self.calls.append(("query", sql, env.copy()))
        assert "PGPASSWORD" not in env
        assert Path(env["PGPASSFILE"]).is_file()
        if sql == operator.IDENTITY_SQL:
            if env["PGHOST"] == SOURCE.host:
                return {**SOURCE_ID, "database_locale": {**SOURCE_LOCALE, **(self.live_locale_override or {})},
                        **({"database_name": "other_database"} if self.source_alias else {})}
            if env["PGDATABASE"] == "postgres":
                return {**CONTROL_ID, **({"server_version_num": self.control_version} if self.control_version else {})}
            identity = {**CONTROL_ID, "database_name": NAME, "database_oid": "16444",
                        "database_locale": {**SOURCE_LOCALE, **(self.target_locale_override or {})}}
            if self.alias:
                identity.update(SOURCE_ID)
            if self.wrong_oid:
                identity["database_oid"] = "16445"
            if self.wrong_server:
                identity["server_address"] = "192.0.2.66"
            return identity
        if "SELECT to_json(EXISTS" in sql:
            return self.exists
        if "SELECT to_json(oid::text)" in sql:
            return "16444"
        if "SELECT to_json(NOT" in sql:
            return self.empty
        pytest.fail("Unexpected synthetic query")

    def run(self, name, args, *, env=None, sql=None, output=None, capture=False):
        self.calls.append((name, args, env.copy() if env else None, sql))
        if env:
            assert SOURCE.password not in " ".join(args)
            assert MAINTENANCE.password not in " ".join(args)
            assert "PGPASSWORD" not in env
            assert Path(env["PGPASSFILE"]).is_file()
        if name == "pg_dump":
            output.write(b"PGDMP\x01synthetic-custom-archive")
        if name == "pg_restore" and self.fail_restore and "--list" not in args:
            raise operator.BackupError("PostgreSQL operation failed; private diagnostics suppressed.")
        return b""


def synthetic_archive(tmp_path):
    return operator.backup(SOURCE, tmp_path / "private_backups", FakeRunner())


def test_custom_backup_binary_checksum_manifest_and_readonly_source(tmp_path):
    runner = FakeRunner()
    archive = operator.backup(SOURCE, tmp_path / "backups", runner)
    assert archive.read_bytes().startswith(b"PGDMP")
    manifest = operator.verify(archive)
    assert manifest["version"] == 2
    assert manifest["source_identity"] == SOURCE_ID
    assert manifest["sha256"] == operator.checksum(archive)
    assert manifest["bytes"] == archive.stat().st_size
    dump = next(row for row in runner.calls if row[0] == "pg_dump")
    assert "--format=custom" in dump[1]
    assert "default_transaction_read_only=on" in dump[2]["PGOPTIONS"]
    assert not Path(dump[2]["PGPASSFILE"]).exists()
    private_contents = b"".join(file.read_bytes() for file in archive.parent.iterdir())
    assert SOURCE.password.encode() not in private_contents


def test_repeated_backup_does_not_overwrite_any_archive(tmp_path):
    first = operator.backup(SOURCE, tmp_path, FakeRunner())
    second = operator.backup(SOURCE, tmp_path, FakeRunner())
    assert first != second and first.exists() and second.exists()


def test_exported_snapshot_is_validated_and_passed_to_custom_dump(tmp_path):
    runner = FakeRunner()
    archive = operator.backup(SOURCE, tmp_path / "backups", runner, "00000004-00000011-1")
    dump = next(row for row in runner.calls if row[0] == "pg_dump")
    assert "--snapshot=00000004-00000011-1" in dump[1]
    assert operator.verify(archive)["external_snapshot_used"] is True
    rejected = FakeRunner()
    with pytest.raises(operator.BackupError, match="Snapshot"):
        operator.backup(SOURCE, tmp_path / "invalid", rejected, "bad;sql")
    assert rejected.calls == []


def test_private_file_requires_exclusive_create(tmp_path):
    path = tmp_path / "existing"
    path.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        operator.private_file(path, b"replacement")
    assert path.read_bytes() == b"original"


def test_source_alias_cannot_backup_a_different_actual_database(tmp_path):
    with pytest.raises(operator.BackupError, match="different database"):
        operator.backup(SOURCE, tmp_path / "not_created", FakeRunner(source_alias=True))
    assert not (tmp_path / "not_created").exists()


@pytest.mark.parametrize("damage", ["archive", "checksum", "manifest_digest", "manifest_bytes", "missing_manifest", "plain_sql"])
def test_checksum_archive_and_manifest_corruption_are_refused(tmp_path, damage):
    path = synthetic_archive(tmp_path)
    manifest_path = Path(str(path) + ".manifest.json")
    if damage == "archive":
        path.write_bytes(path.read_bytes() + b"tampered")
    elif damage == "checksum":
        Path(str(path) + ".sha256").write_text("0" * 64 + "  " + path.name)
    elif damage == "missing_manifest":
        manifest_path.unlink()
    elif damage == "plain_sql":
        path.write_bytes(b"DROP DATABASE live_database;")
    else:
        manifest = json.loads(manifest_path.read_text())
        manifest["sha256" if damage == "manifest_digest" else "bytes"] = "0" * 64 if damage == "manifest_digest" else 1
        manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(operator.BackupError):
        operator.verify(path)


@pytest.mark.parametrize("name", ["postgres", "template0", "template1", "live_database", "Uppercase", "a;DROP_DATABASE", "a/b", "", "a" * 64])
def test_live_default_and_unsafe_target_names_fail_before_connection(tmp_path, name):
    path = synthetic_archive(tmp_path)
    runner = FakeRunner()
    with pytest.raises(operator.BackupError, match="new lowercase"):
        operator.restore(SOURCE, MAINTENANCE, name, path, runner)
    assert runner.calls == []


def test_existing_even_empty_target_is_refused_without_create_or_restore(tmp_path):
    path = synthetic_archive(tmp_path)
    runner = FakeRunner(exists=True)
    with pytest.raises(operator.BackupError, match="already exists"):
        operator.restore(SOURCE, MAINTENANCE, NAME, path, runner)
    assert not any(row[0] == "psql" for row in runner.calls)
    assert not any(row[0] == "pg_restore" and "--list" not in row[1] for row in runner.calls)


@pytest.mark.parametrize("configuration", [{"alias": True}, {"wrong_oid": True}, {"wrong_server": True}, {"empty": False}])
def test_actual_target_identity_and_occupancy_are_verified_before_restore(tmp_path, configuration):
    path = synthetic_archive(tmp_path)
    runner = FakeRunner(**configuration)
    with pytest.raises(operator.BackupError):
        operator.restore(SOURCE, MAINTENANCE, NAME, path, runner)
    assert any(row[0] == "psql" for row in runner.calls)
    assert not any(row[0] == "pg_restore" and "--list" not in row[1] for row in runner.calls)


def test_restore_is_single_transaction_into_new_template0_database(tmp_path):
    path = synthetic_archive(tmp_path)
    runner = FakeRunner()
    operator.restore(SOURCE, MAINTENANCE, NAME, path, runner)
    creation = next(row for row in runner.calls if row[0] == "psql")
    assert creation[3] == (f'CREATE DATABASE "{NAME}" TEMPLATE template0 ENCODING \'UTF8\' '
                           "LOCALE_PROVIDER builtin BUILTIN_LOCALE 'C.UTF-8' LC_COLLATE 'C.UTF-8' LC_CTYPE 'C.UTF-8';")
    restoring = next(row for row in runner.calls if row[0] == "pg_restore" and "--list" not in row[1])
    assert {"--single-transaction", "--exit-on-error", "--no-owner", "--no-acl", "--no-tablespaces"}.issubset(restoring[1])
    all_commands = repr([row[:2] for row in runner.calls])
    assert "--clean" not in all_commands and "DROP DATABASE" not in all_commands and "--create" not in all_commands


def test_restore_failure_never_drops_or_replaces_any_database(tmp_path):
    path = synthetic_archive(tmp_path)
    runner = FakeRunner(fail_restore=True)
    with pytest.raises(operator.BackupError):
        operator.restore(SOURCE, MAINTENANCE, NAME, path, runner)
    assert not any("DROP" in repr(row) for row in runner.calls)


def test_archive_wrong_source_identity_fails_before_create(tmp_path):
    path = synthetic_archive(tmp_path)
    runner = FakeRunner(source_alias=True)
    with pytest.raises(operator.BackupError, match="source database identity"):
        operator.restore(SOURCE, MAINTENANCE, NAME, path, runner)
    assert not any(row[0] == "psql" for row in runner.calls)


def change_manifest_locale(path, changes, *, missing=False):
    manifest_path = Path(str(path) + ".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    if missing:
        manifest["source_identity"].pop("database_locale")
    else:
        manifest["source_identity"]["database_locale"].update(changes)
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize("changes", [
    {"encoding": 8}, {"provider": "c"}, {"provider": "i"}, {"locale": "arbitrary_locale"},
    {"collate": "en_US.UTF-8"}, {"ctype": "en_US.UTF-8"}, {"icu_rules": "arbitrary_rules"},
    {"version": "old_version"}, {"actual_version": "other_provider_version"},
])
def test_unsupported_source_locale_fails_before_connection_or_creation(tmp_path, changes):
    archive = synthetic_archive(tmp_path)
    change_manifest_locale(archive, changes)
    runner = FakeRunner()
    with pytest.raises(operator.BackupError, match="Source locale"):
        operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner)
    assert runner.calls == []


def test_archive_without_locale_metadata_is_refused(tmp_path):
    archive = synthetic_archive(tmp_path)
    change_manifest_locale(archive, {}, missing=True)
    with pytest.raises(operator.BackupError, match="locale metadata"):
        operator.verify(archive)


def test_legacy_archive_requires_new_locale_aware_manifest(tmp_path):
    archive = synthetic_archive(tmp_path)
    path = Path(str(archive) + ".manifest.json")
    manifest = json.loads(path.read_text())
    manifest["version"] = 1
    path.write_text(json.dumps(manifest))
    with pytest.raises(operator.BackupError, match="locale-aware"):
        operator.verify(archive)


@pytest.mark.parametrize("changes", [
    {"encoding": 8}, {"provider": "c"}, {"locale": "C"}, {"collate": "C"}, {"ctype": "C"},
    {"version": "old_version"}, {"actual_version": "other_provider_version"}, {"icu_rules": "changed"},
])
def test_target_locale_is_crosschecked_before_any_object_restore(tmp_path, changes):
    archive = synthetic_archive(tmp_path)
    runner = FakeRunner(target_locale_override=changes)
    with pytest.raises(operator.BackupError, match="Target encoding/provider/locale"):
        operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner)
    assert any(row[0] == "psql" for row in runner.calls)
    assert not any(row[0] == "pg_restore" and "--list" not in row[1] for row in runner.calls)


def test_live_source_locale_change_since_backup_is_refused_before_create(tmp_path):
    archive = synthetic_archive(tmp_path)
    runner = FakeRunner(live_locale_override={"ctype": "C"})
    with pytest.raises(operator.BackupError, match="Source locale changed"):
        operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner)
    assert not any(row[0] == "psql" for row in runner.calls)


def test_different_target_server_major_is_refused_before_create(tmp_path):
    archive = synthetic_archive(tmp_path)
    runner = FakeRunner(control_version=170006)
    with pytest.raises(operator.BackupError, match="same PostgreSQL server major"):
        operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner)
    assert not any(row[0] == "psql" for row in runner.calls)


def test_builtin_cross_os_exception_requires_explicit_flag_and_keeps_provider_semantics(tmp_path, capsys):
    archive = synthetic_archive(tmp_path)
    runner = FakeRunner(target_locale_override={"collate": "C", "ctype": "C"})
    operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner, allow_os_locale_difference=True)
    creation = next(row for row in runner.calls if row[0] == "psql")
    assert creation[3] == (f'CREATE DATABASE "{NAME}" TEMPLATE template0 ENCODING \'UTF8\' '
                           "LOCALE_PROVIDER builtin BUILTIN_LOCALE 'C.UTF-8';")
    assert "COLLATION_VERSION" not in creation[3]
    assert "LC_COLLATE" not in creation[3] and "LC_CTYPE" not in creation[3]
    assert "Promotion has not been verified" in capsys.readouterr().err


def test_cross_os_exception_is_refused_for_non_loopback_target(tmp_path):
    archive = synthetic_archive(tmp_path)
    remote = operator.parse_connection("postgresql://operator:synthetic@target.example.test/postgres?sslmode=require")
    runner = FakeRunner()
    with pytest.raises(operator.BackupError, match="isolated loopback"):
        operator.restore(SOURCE, remote, NAME, archive, runner, allow_os_locale_difference=True)
    assert runner.calls == []


@pytest.mark.parametrize("changes", [
    {"encoding": 8}, {"provider": "c"}, {"locale": "C"},
    {"version": "old_version"}, {"actual_version": "other_provider_version"}, {"icu_rules": "changed"},
])
def test_cross_os_exception_never_bypasses_builtin_encoding_locale_or_versions(tmp_path, changes):
    archive = synthetic_archive(tmp_path)
    runner = FakeRunner(target_locale_override={"collate": "C", "ctype": "C", **changes})
    with pytest.raises(operator.BackupError, match="Target encoding/provider/locale"):
        operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner, allow_os_locale_difference=True)
    assert not any(row[0] == "pg_restore" and "--list" not in row[1] for row in runner.calls)


def test_cross_os_exception_is_not_available_for_other_supported_builtin_locale(tmp_path):
    archive = synthetic_archive(tmp_path)
    change_manifest_locale(archive, {"locale": "C", "collate": "C", "ctype": "C", "version": None, "actual_version": None})
    runner = FakeRunner()
    with pytest.raises(operator.BackupError, match="isolated loopback"):
        operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner, allow_os_locale_difference=True)
    assert runner.calls == []


def test_source_unavailable_recovery_never_creates_source_passfile_or_attempts_source_network(tmp_path, monkeypatch, capsys):
    archive = synthetic_archive(tmp_path)
    connections = []
    real_environment = operator.connection_environment
    def target_only_environment(connection):
        assert connection.host != SOURCE.host, "Source passfile/context must never be created during outage recovery"
        connections.append(connection.database)
        return real_environment(connection)
    monkeypatch.setattr(operator, "connection_environment", target_only_environment)
    class SourceBlockedRunner(FakeRunner):
        def query(self, env, sql):
            assert env["PGHOST"] != SOURCE.host, "No source query may run during outage recovery"
            return super().query(env, sql)
        def run(self, name, args, **kwargs):
            assert not kwargs.get("env") or kwargs["env"]["PGHOST"] != SOURCE.host
            return super().run(name, args, **kwargs)
    runner = SourceBlockedRunner()
    operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner, source_unavailable=True)
    assert connections == ["postgres", NAME]
    assert any(row[0] == "pg_restore" and "--list" not in row[1] for row in runner.calls)
    warning = capsys.readouterr().err
    assert "Live source identity has not been verified" in warning and "Promotion has not been verified" in warning


def test_source_unavailable_does_not_relax_archive_source_name_guard(tmp_path):
    archive = synthetic_archive(tmp_path)
    other_source = operator.parse_connection(SOURCE_URL.replace("/live_database?", "/other_database?"))
    runner = FakeRunner()
    with pytest.raises(operator.BackupError, match="source database name matching"):
        operator.restore(other_source, MAINTENANCE, NAME, archive, runner, source_unavailable=True)
    assert runner.calls == []


def test_source_unavailable_is_restricted_to_loopback_restore_target(tmp_path):
    archive = synthetic_archive(tmp_path)
    remote = operator.parse_connection("postgresql://operator:synthetic@target.example.test/postgres?sslmode=require")
    runner = FakeRunner()
    with pytest.raises(operator.BackupError, match="isolated loopback"):
        operator.restore(SOURCE, remote, NAME, archive, runner, source_unavailable=True)
    assert runner.calls == []


def test_source_unavailable_existing_empty_target_is_still_refused_without_mutation(tmp_path):
    archive = synthetic_archive(tmp_path)
    runner = FakeRunner(exists=True)
    with pytest.raises(operator.BackupError, match="already exists"):
        operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner, source_unavailable=True)
    assert not any(row[0] == "psql" for row in runner.calls)
    assert not any(row[0] == "pg_restore" and "--list" not in row[1] for row in runner.calls)
    assert not any(row[2] and row[2].get("PGHOST") == SOURCE.host for row in runner.calls)


@pytest.mark.parametrize("configuration", [{"empty": False}, {"alias": True}, {"wrong_oid": True}, {"wrong_server": True}])
def test_source_unavailable_keeps_target_identity_and_empty_guards(tmp_path, configuration):
    archive = synthetic_archive(tmp_path)
    runner = FakeRunner(**configuration)
    with pytest.raises(operator.BackupError):
        operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner, source_unavailable=True)
    assert not any(row[0] == "pg_restore" and "--list" not in row[1] for row in runner.calls)
    assert not any(row[2] and row[2].get("PGHOST") == SOURCE.host for row in runner.calls)


def test_source_unavailable_keeps_checksum_guard_before_any_connection(tmp_path):
    archive = synthetic_archive(tmp_path)
    archive.write_bytes(archive.read_bytes() + b"synthetic-tamper")
    runner = FakeRunner()
    with pytest.raises(operator.BackupError, match="checksum"):
        operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner, source_unavailable=True)
    assert runner.calls == []


def test_source_unavailable_supports_explicit_local_cross_os_drill_only(tmp_path, capsys):
    archive = synthetic_archive(tmp_path)
    runner = FakeRunner(target_locale_override={"collate": "C", "ctype": "C"})
    operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner,
                     source_unavailable=True, allow_os_locale_difference=True)
    assert not any(row[2] and row[2].get("PGHOST") == SOURCE.host for row in runner.calls)
    assert "different OS LC_COLLATE/LC_CTYPE" in capsys.readouterr().err


def test_cli_source_unavailable_plan_only_parses_source_configuration_offline(tmp_path, monkeypatch, capsys):
    archive = synthetic_archive(tmp_path)
    source_file, target_file = tmp_path / ".env.source", tmp_path / ".env.target"
    source_file.write_text("DATABASE_URL=" + SOURCE_URL + "\n")
    target_file.write_text("DATABASE_URL=postgresql://local_operator:synthetic@127.0.0.1:55432/postgres?sslmode=disable\n")
    monkeypatch.setattr(operator, "connection_environment", lambda *args: pytest.fail("Offline plan must not create connection contexts"))
    assert operator.main(["restore", "--source-env-file", str(source_file), "--target-env-file", str(target_file),
                          "--target-database", NAME, "--backup-file", str(archive), "--source-unavailable"]) == 0
    assert "OFFLINE PLAN" in capsys.readouterr().out


def test_passfile_escaping_cleanup_and_no_ambient_credentials(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "ambient-secret-must-not-leak")
    monkeypatch.setenv("PGSERVICE", "ambient-service")
    monkeypatch.setenv("DATABASE_URL", "ambient-database")
    with operator.connection_environment(SOURCE) as env:
        passfile = Path(env["PGPASSFILE"])
        assert passfile.read_text() == "source.example.test:5432:live_database:synthetic_user:synthetic\\:password\\\\value\n"
        assert "PGPASSWORD" not in env and "PGSERVICE" not in env and "DATABASE_URL" not in env
        assert SOURCE.password not in str(env)
    assert not passfile.exists()


@pytest.mark.parametrize("url", [
    "sqlite:///file.db", "postgresql://user:password@remote.example.test/db",
    "postgresql://user:password@remote.example.test/db?sslmode=disable",
    "postgresql://user:password@remote.example.test/db?sslmode=require&sslmode=disable",
    "postgresql://user:password@remote.example.test/db?sslmode=require&options=arbitrary",
    "postgresql://user:password@remote.example.test:0/db?sslmode=require",
    "postgresql://user:password@remote.example.test/db?sslmode=require&connect_timeout=999",
    "postgresql://user:password@remote.example.test/db?sslmode=require&channel_binding=invalid",
    "postgresql://user:password@remote.example.test/db?sslmode=require#secret",
    "postgresql://user:password@remote.example.test/db%0A?sslmode=require",
])
def test_invalid_connection_errors_never_echo_url_values(url):
    with pytest.raises(operator.BackupError) as error:
        operator.parse_connection(url)
    assert url not in str(error.value) and "password" not in str(error.value)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_explicit_loopback_only_can_disable_tls(host):
    assert operator.parse_connection(f"postgresql://u:p@{host}/postgres?sslmode=disable").database == "postgres"


def test_cli_offline_backup_never_connects_or_creates_files(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env.source"
    env_file.write_text("DATABASE_URL=" + SOURCE_URL + "\n")
    output = tmp_path / "must_not_exist"
    monkeypatch.setattr(operator, "backup", lambda *args: pytest.fail("Offline invocation must not connect"))
    assert operator.main(["backup", "--source-env-file", str(env_file), "--output-directory", str(output)]) == 0
    assert not output.exists()
    console = capsys.readouterr()
    assert "OFFLINE PLAN" in console.out and SOURCE.password not in console.out + console.err


def test_cli_error_sanitizes_unknown_arguments(capsys):
    with pytest.raises(SystemExit) as error:
        operator.main(["backup", "--source-env-file", "file", "--password", "synthetic_private_value"])
    assert error.value.code == 2
    assert "synthetic_private_value" not in capsys.readouterr().err


def test_subprocess_failure_hides_provider_stderr(monkeypatch, capsys):
    monkeypatch.setattr(operator, "pg_binary", lambda *args: "synthetic-psql")
    monkeypatch.setattr(operator.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=b"", stderr=b"PRIVATE_PROVIDER_PASSWORD"))
    with pytest.raises(operator.BackupError) as error:
        operator.PgRunner().run("psql", ["-X"])
    assert "PRIVATE_PROVIDER_PASSWORD" not in str(error.value) + repr(capsys.readouterr())


def test_psql_preflight_is_readonly_and_uses_json_output(monkeypatch):
    calls = []
    runner = operator.PgRunner()
    def run(name, args, **kwargs):
        calls.append((name, args, kwargs))
        return b"true\n"
    monkeypatch.setattr(runner, "run", run)
    assert runner.query({}, "SELECT true;") is True
    assert calls[0][2]["sql"].startswith("BEGIN READ ONLY;")
    assert "ON_ERROR_STOP=1" in calls[0][1]


def test_restore_preflights_use_real_psql_json_serialization(tmp_path):
    """Exercise PgRunner.query, including psql's native t/f boolean hazard.

    The older FakeRunner returned Python booleans regardless of SQL output and
    could not detect missing to_json wrappers in the real operator workflow.
    """
    archive = synthetic_archive(tmp_path)

    class PsqlSerializationRunner(operator.PgRunner):
        def __init__(self):
            super().__init__()
            self.sql_calls = []

        def run(self, name, args, *, env=None, sql=None, output=None, capture=False):
            if name != "psql" or not capture:
                return b""
            self.sql_calls.append(sql)
            if operator.IDENTITY_SQL in sql:
                if env["PGHOST"] == SOURCE.host:
                    identity = SOURCE_ID
                elif env["PGDATABASE"] == "postgres":
                    identity = CONTROL_ID
                else:
                    identity = {**CONTROL_ID, "database_name": NAME, "database_oid": "16444", "database_locale": SOURCE_LOCALE}
                return (json.dumps(identity) + "\n").encode()
            if "pg_database WHERE datname" in sql and "EXISTS" in sql:
                return b"false\n" if "SELECT to_json(EXISTS" in sql else b"f\n"
            if "SELECT to_json(oid::text)" in sql:
                return b'"16444"\n'
            if "pg_largeobject_metadata" in sql:
                return b"true\n" if "SELECT to_json(NOT" in sql else b"t\n"
            pytest.fail("Unexpected SQL serialization probe")

    runner = PsqlSerializationRunner()
    operator.restore(SOURCE, MAINTENANCE, NAME, archive, runner)
    assert any("SELECT to_json(EXISTS" in sql for sql in runner.sql_calls)
    assert any("SELECT to_json(NOT" in sql for sql in runner.sql_calls)


@pytest.mark.parametrize("raw_boolean", [b"t\n", b"f\n"])
def test_native_psql_non_json_boolean_fails_safely(monkeypatch, raw_boolean):
    runner = operator.PgRunner()
    monkeypatch.setattr(runner, "run", lambda *args, **kwargs: raw_boolean)
    with pytest.raises(operator.BackupError, match="unexpected response"):
        runner.query({}, "SELECT true;")


def test_windows_acl_reset_then_removes_inheritance_before_grant(monkeypatch, tmp_path):
    # Restore the real helper replaced by the autouse fixture.
    spec = importlib.util.spec_from_file_location("isolated_postgres_backup_acl", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=b'"synthetic-user","S-1-5-21-123-456-789-1001"\n', stderr=b"")
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt", environ={"SystemRoot": "synthetic-windows"}))
    module.restrict_path(tmp_path, directory=True)
    assert calls[1][-1] == "/reset"
    assert calls[2][-3:] == ["/inheritance:r", "/grant:r", "*S-1-5-21-123-456-789-1001:(OI)(CI)F"]
