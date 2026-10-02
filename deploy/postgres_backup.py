"""Explicit PostgreSQL custom archives and restoration into a newly created database.

No application modules, dotenv defaults or provider SDKs are imported. Commands
without --apply validate configuration offline. Connection strings/passwords
never appear in command arguments or diagnostics. pg_dump/pg_restore behavior:
https://www.postgresql.org/docs/current/app-pgdump.html
https://www.postgresql.org/docs/current/app-pgrestore.html

Archives contain sensitive application data, but not object-store files, global
roles or application encryption keys. They need separate encrypted offsite
storage. This tool never drops databases, cleans objects or promotes a restore.
Locale-preserving restore currently supports only UTF8 with PostgreSQL's builtin
provider on the same server major version. Other providers/locales are refused.
An explicit --allow-os-locale-difference is restricted to a loopback restore and
builtin C.UTF-8. It permits only differing OS LC_COLLATE/LC_CTYPE metadata; the
builtin locale, encoding and recorded/actual collation versions must match.
Such an isolated cross-OS drill does not establish promotion readiness.
--source-unavailable permits a loopback-only recovery drill without any source
network access. Source configuration/name must match the archive's identity;
live identity is explicitly unverified, while every target guard still applies.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qsl, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SNAPSHOT_ID = re.compile(r"^[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+$")
DEFAULT_DATABASES = {"postgres", "template0", "template1"}
BUILTIN_LOCALES = {"C", "C.UTF-8", "PG_UNICODE_FAST"}
LIBC_LOCALE_SETTINGS = {"C", "C.UTF-8", "POSIX"}
BASE_ENVIRONMENT = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME", "LANG", "LC_ALL"}


class BackupError(Exception):
    """Only fixed, sanitized messages are passed to this exception."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid arguments. Use --help for supported options.\n")


@dataclass(frozen=True)
class Connection:
    host: str
    port: int
    user: str
    password: str
    database: str
    options: tuple[tuple[str, str], ...]


def loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parse_connection(value: str) -> Connection:
    try:
        parsed = urlsplit(value)
        port = parsed.port if parsed.port is not None else 5432
        host = parsed.hostname or ""
        user, password = unquote(parsed.username or ""), unquote(parsed.password or "")
        database = unquote(parsed.path[1:]) if parsed.path.startswith("/") else ""
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except (ValueError, UnicodeError):
        raise BackupError("PostgreSQL connection configuration is invalid.") from None
    parts = (host, user, password, database)
    if (parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}
            or not all(parts) or parsed.fragment or not 1 <= port <= 65535
            or "/" in database or any(any(ord(c) < 32 or ord(c) == 127 for c in part) for part in parts)):
        raise BackupError("A complete PostgreSQL connection configuration is required.")
    allowed = {"sslmode", "sslrootcert", "sslcert", "sslkey", "channel_binding", "connect_timeout", "application_name"}
    if len(dict(pairs)) != len(pairs) or any(key not in allowed for key, _ in pairs):
        raise BackupError("Connection configuration contains unsupported or repeated options.")
    if any(not val or any(ord(c) < 32 or ord(c) == 127 for c in val) for _, val in pairs):
        raise BackupError("Connection configuration contains invalid option values.")
    options = dict(pairs)
    loopback = loopback_host(host)
    mode = options.get("sslmode", "")
    if mode not in {"require", "verify-ca", "verify-full"} and not (loopback and mode == "disable"):
        raise BackupError("Explicit PostgreSQL TLS is required; disable is permitted only for a loopback host.")
    if "connect_timeout" in options and (not options["connect_timeout"].isdigit() or not 1 <= int(options["connect_timeout"]) <= 30):
        raise BackupError("Connection timeout must be between 1 and 30 seconds.")
    if options.get("channel_binding", "prefer") not in {"disable", "prefer", "require"}:
        raise BackupError("Channel binding configuration is invalid.")
    return Connection(host, port, user, password, database, tuple(sorted(options.items())))


def read_connection(path: Path) -> Connection:
    # Reuse the existing strict, non-expanding, explicit-file dotenv parser.
    sys.path.insert(0, str(ROOT / "deploy"))
    try:
        from vercel_config import ConfigError, read_env
        try:
            values = read_env(path)
        except ConfigError:
            raise BackupError("The explicit configuration file could not be read safely.") from None
    finally:
        sys.path.pop(0)
    return parse_connection(values.get("DATABASE_URL", ""))


def restrict_path(path: Path, *, directory: bool = False) -> None:
    """Remove inherited/explicit broad access before writing private data."""
    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        return
    # Reset removes explicit ACEs; removing inheritance then leaves only the
    # current operator's grant. Paths and public Windows SID are not credentials.
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    try:
        who = subprocess.run([str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
                             capture_output=True, timeout=15, check=False)
        sid = re.findall(rb"S-1-[0-9-]+", who.stdout)
        if who.returncode or len(sid) != 1:
            raise BackupError("Could not determine private file permissions.")
        grant = "*" + sid[0].decode("ascii") + (":(OI)(CI)F" if directory else ":F")
        for args in (("/reset",), ("/inheritance:r", "/grant:r", grant)):
            result = subprocess.run([str(system / "icacls.exe"), str(path), *args],
                                    capture_output=True, timeout=15, check=False)
            if result.returncode:
                raise BackupError("Could not restrict private file permissions.")
    except (OSError, subprocess.TimeoutExpired):
        raise BackupError("Could not restrict private file permissions.") from None


def private_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        restrict_path(path)
        handle.write(content)


def private_directory(parent: Path, prefix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    directory = parent / (prefix + secrets.token_hex(12))
    directory.mkdir(mode=0o700)
    restrict_path(directory, directory=True)
    return directory


def pg_binary(name: str, directory: Path | None) -> str:
    path = directory / (name + (".exe" if os.name == "nt" else "")) if directory else None
    executable = str(path) if path is not None and path.is_file() else (shutil.which(name) if directory is None else None)
    if not executable:
        raise BackupError("Required PostgreSQL client binary is unavailable; provide --pg-bin-directory.")
    return executable


def pass_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


@contextmanager
def connection_environment(connection: Connection):
    with tempfile.TemporaryDirectory(prefix="danaconnect-pg-private-") as directory:
        root = Path(directory)
        restrict_path(root, directory=True)
        passfile = root / "pgpass"
        row = ":".join(pass_escape(str(value)) for value in
                       (connection.host, connection.port, connection.database, connection.user, connection.password)) + "\n"
        private_file(passfile, row.encode("utf-8"))
        env = {key: value for key, value in os.environ.items() if key.upper() in BASE_ENVIRONMENT}
        env.update({"PGHOST": connection.host, "PGPORT": str(connection.port), "PGUSER": connection.user,
                    "PGDATABASE": connection.database, "PGPASSFILE": str(passfile), "PGCONNECT_TIMEOUT": "10",
                    "PGAPPNAME": "danaconnect-backup-operator", "PGCLIENTENCODING": "UTF8"})
        option_keys = {"sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT", "sslcert": "PGSSLCERT",
                       "sslkey": "PGSSLKEY", "channel_binding": "PGCHANNELBINDING", "connect_timeout": "PGCONNECT_TIMEOUT",
                       "application_name": "PGAPPNAME"}
        env.update({option_keys[key]: value for key, value in connection.options})
        yield env


class PgRunner:
    def __init__(self, directory: Path | None = None, timeout: int = 600):
        self.directory, self.timeout = directory, timeout

    def run(self, name: str, args: list[str], *, env: dict[str, str] | None = None,
            sql: str | None = None, output=None, capture: bool = False) -> bytes:
        try:
            result = subprocess.run([pg_binary(name, self.directory), *args],
                                    input=sql.encode("utf-8") if sql is not None else None,
                                    stdout=output if output is not None else (subprocess.PIPE if capture else subprocess.DEVNULL),
                                    stderr=subprocess.PIPE, env=env or {key: val for key, val in os.environ.items() if key.upper() in BASE_ENVIRONMENT},
                                    timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise BackupError("PostgreSQL operation failed or timed out; no provider diagnostics were disclosed.") from None
        if result.returncode:
            raise BackupError("PostgreSQL operation failed; no provider diagnostics were disclosed. A new restore database may remain empty or incomplete.")
        if result.stderr:
            # Warnings can contain private object names. Never echo them.
            print("PostgreSQL emitted a warning; its private text was suppressed.", file=sys.stderr)
        return result.stdout or b""

    def query(self, env: dict[str, str], sql: str):
        raw = self.run("psql", ["-X", "-w", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1"], env=env,
                       sql="BEGIN READ ONLY; SET LOCAL statement_timeout = '15s';\n" + sql + "\nCOMMIT;", capture=True)
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise BackupError("PostgreSQL preflight returned an unexpected response.") from None


IDENTITY_SQL = """SELECT row_to_json(i) FROM (
SELECT current_database() AS database_name,
db.oid::text AS database_oid,
inet_server_addr()::text AS server_address, inet_server_port() AS server_port,
current_setting('server_version_num')::integer AS server_version_num,
json_build_object('encoding', db.encoding, 'provider', db.datlocprovider,
    'collate', db.datcollate, 'ctype', db.datctype, 'locale', db.datlocale,
    'icu_rules', db.daticurules, 'version', db.datcollversion,
    'actual_version', pg_database_collation_actual_version(db.oid)) AS database_locale
FROM pg_database db WHERE db.datname = current_database()) i;"""


def checked_locale(value) -> dict:
    if (not isinstance(value, dict) or type(value.get("encoding")) is not int
            or not isinstance(value.get("provider"), str) or value["provider"] not in {"b", "c", "i"}
            or any(not isinstance(value.get(key), str) or not value[key] for key in ("collate", "ctype"))
            or any(key not in value or (value[key] is not None and not isinstance(value[key], str))
                   for key in ("locale", "icu_rules", "version", "actual_version"))):
        raise BackupError("Database locale metadata could not be verified; a new archive with locale metadata is required.")
    return value


def supported_restore_locale(identity: dict) -> dict:
    locale = checked_locale(identity.get("database_locale"))
    if (locale["encoding"] != 6 or locale["provider"] != "b" or locale["locale"] not in BUILTIN_LOCALES
            or locale["collate"] not in LIBC_LOCALE_SETTINGS or locale["ctype"] not in LIBC_LOCALE_SETTINGS
            or locale["icu_rules"] is not None or locale["version"] != locale["actual_version"]
            or identity["server_version_num"] < 170000):
        raise BackupError("Source locale is unsupported or its recorded collation version differs from the actual provider version; restoration was refused.")
    return locale


def creation_sql(name: str, locale: dict, allow_os_locale_difference: bool = False) -> str:
    # name and every interpolated locale identifier are already whitelisted.
    statement = (f'CREATE DATABASE "{name}" TEMPLATE template0 ENCODING \'UTF8\' '
                 f"LOCALE_PROVIDER builtin BUILTIN_LOCALE '{locale['locale']}'")
    if not allow_os_locale_difference:
        statement += f" LC_COLLATE '{locale['collate']}' LC_CTYPE '{locale['ctype']}'"
    return statement + ";"


def validate_os_locale_exception(locale: dict, maintenance: Connection, allowed: bool) -> None:
    if allowed and (not loopback_host(maintenance.host) or locale["provider"] != "b"
                    or locale["encoding"] != 6 or locale["locale"] != "C.UTF-8"):
        raise BackupError("The OS locale exception is restricted to an isolated loopback target and source UTF8/builtin/C.UTF-8.")


def validate_unavailable_source(source: Connection, maintenance: Connection, recorded: dict, unavailable: bool) -> None:
    if unavailable and (not loopback_host(maintenance.host) or source.database != recorded["database_name"]):
        raise BackupError("Source-unavailable recovery requires an isolated loopback target and a source database name matching the archive identity.")


def locale_matches(source: dict, target: dict, allow_os_locale_difference: bool) -> bool:
    keys = ("encoding", "provider", "locale", "icu_rules", "version", "actual_version")
    if not allow_os_locale_difference:
        keys += ("collate", "ctype")
    return all(source[key] == target[key] for key in keys)


def checked_identity(value) -> dict:
    if (not isinstance(value, dict) or not isinstance(value.get("database_name"), str)
            or not value["database_name"] or not str(value.get("database_oid", "")).isdigit()
            or not isinstance(value.get("server_address"), str) or not value["server_address"]
            or not isinstance(value.get("server_port"), int) or not isinstance(value.get("server_version_num"), int)):
        raise BackupError("Database connection identity could not be verified.")
    checked_locale(value.get("database_locale"))
    return value


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup(connection: Connection, output_directory: Path, runner: PgRunner, snapshot: str | None = None) -> Path:
    if snapshot is not None and not SNAPSHOT_ID.fullmatch(snapshot):
        raise BackupError("Snapshot identifier is invalid.")
    with connection_environment(connection) as env:
        identity = checked_identity(runner.query(env, IDENTITY_SQL))
        if identity["database_name"] != connection.database:
            raise BackupError("Source connection resolves to a different database; refusing backup.")
        directory = private_directory(output_directory, "danaconnect-")
        path = directory / "database.dump"
        # pg_dump emits binary stdout directly into an exclusive, private file.
        with path.open("xb") as handle:
            restrict_path(path)
            dump_args = ["--format=custom", "--no-password", "--lock-wait-timeout=10s"]
            if snapshot is not None:
                dump_args.append("--snapshot=" + snapshot)
            runner.run("pg_dump", dump_args,
                       env={**env, "PGOPTIONS": "-c default_transaction_read_only=on"}, output=handle)
        runner.run("pg_restore", ["--list", str(path)])
        digest = checksum(path)
        private_file(Path(str(path) + ".sha256"), (digest + "  " + path.name + "\n").encode("ascii"))
        manifest = {"version": 2, "format": "postgresql-custom", "sha256": digest,
                    "bytes": path.stat().st_size, "created_at": datetime.now(timezone.utc).isoformat(),
                    "source_identity": identity, "external_snapshot_used": snapshot is not None}
        private_file(Path(str(path) + ".manifest.json"), (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8"))
        return path


def verify(path: Path) -> dict:
    try:
        files = (path, Path(str(path) + ".sha256"), Path(str(path) + ".manifest.json"))
        if any(item.is_symlink() or not item.is_file() for item in files):
            raise BackupError("Archive, checksum and manifest must be regular files.")
        with path.open("rb") as handle:
            if handle.read(5) != b"PGDMP":
                raise BackupError("Only a PostgreSQL custom-format archive is accepted.")
        expected = files[1].read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[a-f0-9]{64}  " + re.escape(path.name), expected):
            raise BackupError("Archive checksum file has an invalid format.")
        digest = checksum(path)
        if expected[:64] != digest:
            raise BackupError("Archive checksum does not match.")
        if files[2].stat().st_size > 16384:
            raise BackupError("Archive manifest is invalid.")
        manifest = json.loads(files[2].read_text(encoding="utf-8"))
        if isinstance(manifest, dict) and manifest.get("version") != 2:
            raise BackupError("Archive manifest version is unsupported; create a new locale-aware archive.")
        if (not isinstance(manifest, dict) or manifest.get("format") != "postgresql-custom"
                or manifest.get("sha256") != digest or manifest.get("bytes") != path.stat().st_size):
            raise BackupError("Archive manifest does not match the archive.")
        checked_identity(manifest.get("source_identity"))
        return manifest
    except (OSError, UnicodeError, ValueError):
        raise BackupError("Archive verification failed; no private file contents were disclosed.") from None


def target_name(value: str, source_names: set[str]) -> str:
    if not DATABASE_NAME.fullmatch(value) or value in DEFAULT_DATABASES or value in source_names:
        raise BackupError("Restore requires a new lowercase database name, different from live and default databases.")
    return value


def restore(source: Connection, maintenance: Connection, name: str, path: Path, runner: PgRunner,
            allow_os_locale_difference: bool = False, source_unavailable: bool = False) -> None:
    manifest = verify(path)
    target_name(name, {source.database, manifest["source_identity"]["database_name"]})
    source_locale = supported_restore_locale(manifest["source_identity"])
    validate_os_locale_exception(source_locale, maintenance, allow_os_locale_difference)
    recorded = manifest["source_identity"]
    validate_unavailable_source(source, maintenance, recorded, source_unavailable)
    # Validate the archive before any database mutation.
    runner.run("pg_restore", ["--list", str(path)])
    with connection_environment(maintenance) as control_env:
        if source_unavailable:
            print("WARNING: Source-unavailable recovery skips all live source connections. Live source identity has not been verified; archive/configuration checks and target guards apply. Promotion has not been verified.", file=sys.stderr)
        else:
            with connection_environment(source) as source_env:
                live = checked_identity(runner.query(source_env, IDENTITY_SQL))
            if (live["database_name"], live["database_oid"]) != (recorded["database_name"], recorded["database_oid"]):
                raise BackupError("Archive does not belong to the current source database identity.")
            if live["database_locale"] != source_locale:
                raise BackupError("Source locale changed since this archive was created; restoration was refused.")
            target_name(name, {source.database, live["database_name"]})
        control = checked_identity(runner.query(control_env, IDENTITY_SQL))
        if control["server_version_num"] // 10000 != recorded["server_version_num"] // 10000:
            raise BackupError("Locale-preserving restore requires the same PostgreSQL server major version; restoration was refused.")
        # actual catalog lookup catches aliases/pooler routes, even an empty
        # existing target. CREATE DATABASE itself closes the existence race.
        exists = runner.query(control_env, f"SELECT to_json(EXISTS (SELECT 1 FROM pg_database WHERE datname = '{name}'));")
        if exists is not False:
            raise BackupError("The target database already exists; empty existing databases are also refused.")
        runner.run("psql", ["-X", "-w", "-q", "-v", "ON_ERROR_STOP=1"], env=control_env,
                   sql=creation_sql(name, source_locale, allow_os_locale_difference))
        expected_oid = runner.query(control_env, f"SELECT to_json(oid::text) FROM pg_database WHERE datname = '{name}';")
        with connection_environment(replace(maintenance, database=name)) as target_env:
            identity = checked_identity(runner.query(target_env, IDENTITY_SQL))
            if (identity["database_name"] != name or identity["database_oid"] != expected_oid
                    or (identity["server_address"], identity["server_port"]) != (control["server_address"], control["server_port"])):
                raise BackupError("Target connection resolves to a different database/server; restoration was refused.")
            if not locale_matches(source_locale, identity["database_locale"], allow_os_locale_difference):
                raise BackupError("Target encoding/provider/locale/collation version does not exactly match the archive source; restoration was refused.")
            if allow_os_locale_difference and any(source_locale[key] != identity["database_locale"][key] for key in ("collate", "ctype")):
                print("WARNING: Isolated restore has different OS LC_COLLATE/LC_CTYPE metadata. Builtin locale, encoding, provider and recorded/actual version match. Promotion has not been verified.", file=sys.stderr)
            empty = runner.query(target_env, """SELECT to_json(NOT (
EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema') OR
EXISTS (SELECT 1 FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname NOT IN ('public','information_schema')) OR
EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema') OR
EXISTS (SELECT 1 FROM pg_extension WHERE extname <> 'plpgsql') OR
EXISTS (SELECT 1 FROM pg_largeobject_metadata)));""")
            if empty is not True:
                raise BackupError("The newly created target is not empty; restoration was refused.")
            runner.run("pg_restore", ["--no-password", "--no-owner", "--no-acl", "--no-tablespaces",
                                      "--single-transaction", "--exit-on-error", "--dbname=" + name, str(path)], env=target_env)


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=SafeParser)
    verify_parser = sub.add_parser("verify", help="Verify custom archive/checksum/manifest offline.")
    verify_parser.add_argument("--backup-file", type=Path, required=True)
    for command in ("backup", "restore"):
        child = sub.add_parser(command, help="Offline validation unless --apply is explicitly supplied.")
        child.add_argument("--source-env-file", type=Path, required=True)
        child.add_argument("--pg-bin-directory", type=Path)
        child.add_argument("--timeout-seconds", type=int, default=600)
        child.add_argument("--apply", action="store_true")
        if command == "backup":
            child.add_argument("--output-directory", type=Path, default=ROOT / "deploy" / "backups")
            child.add_argument("--snapshot", help="Optional exported snapshot ID; the exporting read-only transaction must remain open.")
        else:
            child.add_argument("--target-env-file", type=Path, required=True, help="Explicit maintenance connection file; never modified.")
            child.add_argument("--target-database", required=True)
            child.add_argument("--backup-file", type=Path, required=True)
            child.add_argument("--allow-os-locale-difference", action="store_true",
                               help="Isolated loopback builtin C.UTF-8 drill only: permit different OS LC_COLLATE/LC_CTYPE; never a promotion check.")
            child.add_argument("--source-unavailable", action="store_true",
                               help="Loopback recovery drill only: skip all source network connections; archive/source-name checks and every target guard remain.")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            verify(args.backup_file)
            print("Archive checksum and manifest verified offline. Restore has not been performed.")
            return 0
        if not 1 <= args.timeout_seconds <= 3600:
            raise BackupError("Operation timeout must be between 1 and 3600 seconds.")
        source = read_connection(args.source_env_file)
        if args.command == "backup" and args.snapshot is not None and not SNAPSHOT_ID.fullmatch(args.snapshot):
            raise BackupError("Snapshot identifier is invalid.")
        runner = PgRunner(args.pg_bin_directory, args.timeout_seconds)
        if args.command == "restore":
            maintenance = read_connection(args.target_env_file)
            manifest = verify(args.backup_file)
            target_name(args.target_database, {source.database, manifest["source_identity"]["database_name"]})
            locale = supported_restore_locale(manifest["source_identity"])
            validate_os_locale_exception(locale, maintenance, args.allow_os_locale_difference)
            validate_unavailable_source(source, maintenance, manifest["source_identity"], args.source_unavailable)
        if not args.apply:
            print("OFFLINE PLAN: configuration validated; no connection opened and no files/databases created. Use --apply to perform the requested operation.")
            return 0
        if args.command == "backup":
            backup(source, args.output_directory, runner, args.snapshot)
            print("Backup created in a new private child directory of the requested output directory. Checksum and manifest written; object files and encryption keys need separate backup.")
        else:
            restore(source, maintenance, args.target_database, args.backup_file, runner,
                    args.allow_os_locale_difference, args.source_unavailable)
            print("Restored into the newly created separate database. The live database was not replaced; promotion is a separate operation.")
        return 0
    except BackupError as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyboardInterrupt):
        print("ERROR: Operation interrupted or failed. Private diagnostics were suppressed; inspect any new restore database before retrying.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
