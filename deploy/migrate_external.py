"""Plan repository migrations offline; explicitly apply them to configured PostgreSQL.

Examples (no connection unless --apply is present):
  python deploy/migrate_external.py
  python deploy/migrate_external.py --expected-current empty
  python deploy/migrate_external.py --apply --env-file deploy/.env.vercel.local \
      --expected-current empty

Use the literal 'empty' for a fresh, dedicated database. This tool does not
seed data, downgrade, create backups, or establish that a backup is restorable.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
VERSIONS = API / "migrations" / "versions"
LOCK_ID = 824310770216
WORKER_FAILURES = {
    10: "Another migration operator holds the migration lock; nothing was upgraded.",
    11: "Database revision does not exactly match --expected-current; nothing was upgraded.",
    12: "Fresh database is not empty; user relations already exist. Nothing was upgraded.",
    13: "Expected application tables are missing; nothing was upgraded.",
    14: "This repository migration layout requires the public schema; nothing was upgraded.",
    15: "Repository migrations changed; review the offline plan before applying.",
    16: "Upgrade did not reach repository head; its transaction was not committed.",
}


class OperatorError(Exception):
    """Only fixed operator messages may be put in this exception."""

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # Argparse's default message can repeat an accidentally supplied secret.
        self.exit(2, "Invalid arguments. Use --help for supported options.\n")


@dataclass(frozen=True)
class Revision:
    revision: str
    parent: str | None
    actions: tuple[tuple[str, int], ...]
    digest: str


def migration_chain() -> list[Revision]:
    """Read Python syntax only; never execute migrations during planning."""
    revisions = {}
    for path in sorted(VERSIONS.glob("*.py")):
        source = path.read_bytes()
        tree = ast.parse(source, filename="repository_migration")
        metadata = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name, value = node.target.id, node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name, value = node.targets[0].id, node.value
            else:
                continue
            if name in {"revision", "down_revision", "depends_on", "branch_labels"}:
                metadata[name] = ast.literal_eval(value)
        revision = metadata.get("revision")
        parent = metadata.get("down_revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[a-zA-Z0-9_]{1,64}", revision):
            raise OperatorError("Repository migration metadata is invalid.")
        if parent is not None and (not isinstance(parent, str) or not re.fullmatch(r"[a-zA-Z0-9_]{1,64}", parent)):
            raise OperatorError("Only one linear repository migration chain is supported.")
        if metadata.get("depends_on") or metadata.get("branch_labels") or revision in revisions:
            raise OperatorError("Only one linear repository migration chain is supported.")
        upgrade = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upgrade"), None)
        if upgrade is None:
            raise OperatorError("Repository migration upgrade is missing.")
        actions = Counter(
            node.func.attr for node in ast.walk(upgrade)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id in {"op", "batch_op"}
        )
        revisions[revision] = Revision(revision, parent, tuple(sorted(actions.items())), hashlib.sha256(source).hexdigest())
    if not revisions:
        raise OperatorError("No repository migrations are available.")
    children = {}
    for row in revisions.values():
        if row.parent is not None and row.parent not in revisions:
            raise OperatorError("Repository migration chain has a missing parent.")
        if row.parent in children:
            raise OperatorError("Only one linear repository migration chain is supported.")
        children[row.parent] = row
    chain = []
    current = children.get(None)
    while current is not None and current not in chain:
        chain.append(current)
        current = children.get(current.revision)
    if len(chain) != len(revisions) or current is not None:
        raise OperatorError("Repository migration chain is incomplete or cyclic.")
    return chain


def chain_digest(chain: list[Revision]) -> str:
    return hashlib.sha256("".join(row.digest for row in chain).encode()).hexdigest()


def environment_digest(values: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def expected_revision(value: str | None, chain: list[Revision]) -> str | None:
    if value is None:
        return None
    if value in {"", "empty"}:
        return "empty"
    if value not in {row.revision for row in chain}:
        raise OperatorError("Expected revision must be a repository revision or 'empty'.")
    return value


def print_plan(chain: list[Revision], expected: str | None):
    print("OFFLINE PLAN: no configuration loaded and no database connection opened.")
    print("Repository head: " + chain[-1].revision)
    print("Expected current revision: " + (expected or "not specified; database state remains unknown"))
    pending = expected in {None, "empty"}
    for row in chain:
        if pending:
            print(row.revision + ": " + ", ".join(f"{name} ({count})" for name, count in row.actions))
        if row.revision == expected:
            pending = True
    if expected == chain[-1].revision:
        print("No upgrades planned; --apply would still verify the database revision.")
    print("Apply requires --apply, --env-file and --expected-current. Only repository head is supported.")
    print("No seed, downgrade or backup is performed. Stop other migration runners before applying.")


def postgres_url(value: str) -> str:
    """Validate transport without opening a socket or printing URL components."""
    if not value or any(character.isspace() for character in value):
        raise OperatorError("A complete PostgreSQL DATABASE_URL is required.")
    parsed = urlsplit(value)
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise OperatorError("Only PostgreSQL with the installed psycopg driver is supported.")
    placeholders = {"replace_me", "changeme", "change_me", "placeholder", "your_password", "your_host"}
    if not parsed.hostname or not parsed.username or not parsed.password or not parsed.path.strip("/") or parsed.fragment:
        raise OperatorError("A complete PostgreSQL DATABASE_URL is required.")
    if parsed.hostname.endswith((".invalid", ".example", "example.com", "example.org", "example.net")) or any(unquote(part).lower() in placeholders or re.search(r"replace[_-]me|your[_-](host|password)|[<>]", unquote(part), re.I) for part in (parsed.hostname, parsed.username, parsed.password)):
        raise OperatorError("DATABASE_URL still contains placeholder configuration.")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise OperatorError("DATABASE_URL port is invalid.")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    allowed = {"sslmode", "sslrootcert", "sslcert", "sslkey", "channel_binding", "connect_timeout", "application_name"}
    if len({key for key, _ in pairs}) != len(pairs) or any(key not in allowed for key, _ in pairs):
        raise OperatorError("DATABASE_URL contains unsupported or repeated connection options.")
    options = dict(pairs)
    if options.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
        raise OperatorError("PostgreSQL TLS is required: set sslmode=require, verify-ca or verify-full.")
    if "connect_timeout" in options and (not options["connect_timeout"].isdigit() or not 1 <= int(options["connect_timeout"]) <= 30):
        raise OperatorError("PostgreSQL connect_timeout must be between 1 and 30 seconds.")
    return urlunsplit(("postgresql+psycopg", parsed.netloc, parsed.path, parsed.query, ""))


def private_environment(values: dict[str, str], chain: list[Revision]) -> dict[str, str]:
    # Retain platform basics; inherited API settings and local credentials do not
    # override the operator's file. Importing Settings takes place in an empty cwd.
    environment = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME", "LANG", "LC_ALL") if key in os.environ}
    tree = ast.parse((API / "app" / "config.py").read_text(encoding="utf-8"))
    settings_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Settings")
    fields = {node.target.id.upper() for node in settings_class.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}
    # Settings.vercel is an explicit environment alias when root enables Vercel.
    fields.add("VERCEL")
    environment.update({key: value for key, value in values.items() if key.upper() in fields})
    environment["DATABASE_URL"] = postgres_url(values.get("DATABASE_URL", ""))
    environment["PYTHONPATH"] = str(API)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["DANACONNECT_MIGRATION_WORKER"] = "1"
    environment["DANACONNECT_MIGRATION_DIGEST"] = chain_digest(chain)
    environment["DANACONNECT_MIGRATION_ENV_DIGEST"] = environment_digest(values)
    return environment


def apply_worker(expected: str, chain: list[Revision], env_file: Path) -> int:
    """Runs only in the isolated child created by an explicit --apply."""
    if os.environ.get("DANACONNECT_MIGRATION_WORKER") != "1" or os.environ.get("DANACONNECT_MIGRATION_DIGEST") != chain_digest(chain):
        raise OperatorError(WORKER_FAILURES[15], 15)
    from vercel_config import read_env
    # An explicit file remains required in the internal mode. Refuse an edited
    # operator file between the parent snapshot and child validation.
    if environment_digest(read_env(env_file)) != os.environ.get("DANACONNECT_MIGRATION_ENV_DIGEST"):
        raise OperatorError("Configuration changed before apply; review it before retrying.")
    from app.config import settings
    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    if settings.environment != "production" or settings.demo_mode or settings.auth_debug_code:
        raise OperatorError("Apply requires valid production configuration with demo and debug disabled.")
    url = postgres_url(settings.database_url)
    config = Config()  # No local .ini logging handlers or development database URL.
    config.set_main_option("script_location", str(API / "migrations"))
    script = ScriptDirectory.from_config(config)
    if script.get_heads() != [chain[-1].revision]:
        raise OperatorError(WORKER_FAILURES[15], 15)
    engine = create_engine(url, poolclass=NullPool, echo=False, connect_args={"connect_timeout": 10})
    try:
        with engine.begin() as connection:
            # The caller owns one transaction. The same physical connection is
            # passed to Alembic, including through a transaction-pooling endpoint.
            # Independent Alembic commands do not honor this cooperative lock.
            connection.exec_driver_sql("SET LOCAL statement_timeout = '5min'")
            connection.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
            if connection.scalar(text("SELECT pg_try_advisory_xact_lock(:lock_id)"), {"lock_id": LOCK_ID}) is not True:
                raise OperatorError(WORKER_FAILURES[10], 10)
            if connection.scalar(text("SELECT current_schema()")) != "public":
                raise OperatorError(WORKER_FAILURES[14], 14)
            current = MigrationContext.configure(connection).get_current_heads()
            wanted = () if expected == "empty" else (expected,)
            if tuple(current) != wanted:
                raise OperatorError(WORKER_FAILURES[11], 11)
            if expected == "empty":
                occupied = connection.scalar(text("""
                    SELECT EXISTS (
                      SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                      WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
                        AND c.relkind IN ('r','p','v','m','f','S')
                        AND NOT (n.nspname='public' AND c.relname='alembic_version' AND c.relkind='r')
                    )
                """))
                if occupied:
                    raise OperatorError(WORKER_FAILURES[12], 12)
            else:
                # A manual version stamp on a tableless DB is not a valid
                # existing installation of any current repository revision.
                present = connection.scalar(text("""
                    SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='public' AND c.relkind IN ('r','p')
                      AND c.relname IN ('users','projects','directions','documents')
                """))
                if present != 4:
                    raise OperatorError(WORKER_FAILURES[13], 13)
            config.attributes['connection'] = connection
            command.upgrade(config, chain[-1].revision)
            actual = MigrationContext.configure(connection).get_current_heads()
            if tuple(actual) != (chain[-1].revision,):
                raise OperatorError(WORKER_FAILURES[16], 16)
    finally:
        engine.dispose()
    return 0


def main() -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Explicitly connect, verify expected state and upgrade to repository head.")
    parser.add_argument("--env-file", type=Path, help="Operator-completed private production configuration; read only with --apply.")
    parser.add_argument("--expected-current", help="Exact repository revision, or the literal 'empty' for a fresh dedicated database.")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        chain = migration_chain()
        expected = expected_revision(args.expected_current, chain)
        if args._worker:
            if not args.apply or args.env_file is None or expected is None:
                raise OperatorError("Explicit apply inputs are missing.")
            return apply_worker(expected, chain, args.env_file)
        print_plan(chain, expected)
        if not args.apply:
            return 0
        if args.env_file is None or expected is None:
            raise OperatorError("Apply requires --env-file and --expected-current.")
        from vercel_config import read_env
        values = read_env(args.env_file.resolve())
        if values.get("ENVIRONMENT") != "production":
            raise OperatorError("The supplied configuration must explicitly select production.")
        environment = private_environment(values, chain)
        print("APPLY requested. Configuration and revision checks will run before upgrading.")
        with tempfile.TemporaryDirectory(prefix="danaconnect-migration-") as isolated:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--_worker", "--apply", "--env-file", str(args.env_file.resolve()), "--expected-current", expected],
                env=environment, cwd=isolated, capture_output=True, timeout=900,
            )
        # Neither SQLAlchemy/Alembic output nor exception text is ever relayed.
        if result.returncode != 0:
            print(WORKER_FAILURES.get(result.returncode, "Migration was not confirmed. Check production configuration, expected revision and database access with the operator. No backup or restore proof was created."))
            return 1
        print("Database revision verified at repository head: " + chain[-1].revision)
        print("No seed, downgrade or backup was performed. Provider availability and restoration remain separate confirmations.")
        return 0
    except OperatorError as error:
        print(str(error))
        return error.exit_code
    except KeyboardInterrupt:
        print("Migration operator interrupted. Database state must be reviewed before retrying.")
        return 130
    except Exception:
        print("Migration operator could not complete. Secret values and internal exception details were suppressed; review configuration and database state before retrying.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
