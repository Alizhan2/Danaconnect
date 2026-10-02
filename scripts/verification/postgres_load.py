"""Bounded synthetic HTTP/concurrency pilot against disposable local PostgreSQL.

Example (the file contains one PostgreSQL URL, never production credentials):
  .venv/Scripts/python.exe scripts/verification/postgres_load.py \
    --database-url-file artifacts/verification/load-db.url \
    --clients 20 --read-rounds 5 --report artifacts/verification/postgres-load.json

Only a literal loopback address and an empty database named dc_pilot_load_* or
danaconnect_load_* are accepted. The runner applies real Alembic migrations,
seeds synthetic .test people and sessions, then launches its own loopback API.
No real mail, Google, storage, AI, workspace dotenv, or existing API is used.
The populated database is retained for inspection; a second run needs a NEW
empty database. This is a correctness pilot, not a cloud capacity guarantee.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
AUTH_SECRET = "synthetic-loopback-load-secret-never-for-deployment"
ORIGIN = "http://127.0.0.1:3999"
DATABASE_PREFIX = re.compile(r"(?:dc_pilot_load_|danaconnect_load_)[a-z0-9_]+\Z")


class PilotError(RuntimeError):
    """Safe diagnostic text; do not echo connection URLs or server exceptions."""


def validate_database_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"postgresql", "postgres", "postgresql+psycopg"}:
        raise PilotError("The pilot requires PostgreSQL with the psycopg driver")
    try:
        loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
        port = parsed.port
    except ValueError:
        raise PilotError("Use a literal loopback PostgreSQL address") from None
    if not loopback or not port or parsed.fragment:
        raise PilotError("A literal loopback address and explicit port are required")
    if not DATABASE_PREFIX.fullmatch(parsed.path.removeprefix("/")):
        raise PilotError("Use a new database named dc_pilot_load_* or danaconnect_load_*")
    # A host/service/options query could bypass the endpoint/name checks above.
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(key not in {"sslmode", "connect_timeout"} for key in query):
        raise PilotError("Connection query permits only sslmode and connect_timeout")
    if any(len(values) != 1 for values in query.values()):
        raise PilotError("Repeated connection parameters are not permitted")
    if query.get("sslmode", ["disable"])[0] not in {"disable", "prefer", "require"}:
        raise PilotError("Unsupported local SSL mode")
    if "connect_timeout" in query:
        try:
            valid_timeout = 1 <= int(query["connect_timeout"][0]) <= 30
        except ValueError:
            valid_timeout = False
        if not valid_timeout:
            raise PilotError("connect_timeout must be between 1 and 30 seconds")
    return "postgresql+psycopg" + value[value.index(":"):]


def clean_environment(database_url: str) -> dict[str, str]:
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP",
               "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HOME"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update({
        "PYTHONPATH": str(ROOT / "apps/api"), "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1", "ENVIRONMENT": "test", "DATABASE_URL": database_url,
        "DATABASE_POOL_MODE": "queue", "AUTH_SECRET": AUTH_SECRET,
        "AUTH_DEBUG_CODE": "false", "DEMO_MODE": "false", "EMAIL_PROVIDER": "none",
        "STORAGE_PROVIDER": "none", "AI_ENABLED": "false", "VERCEL": "false",
        "TRUSTED_ORIGINS": json.dumps([ORIGIN]), "FRONTEND_URL": ORIGIN,
            "DC_SYNTHETIC_PILOT_CHILD": "1",
    })
    return env


def percentile(values: list[float], percent: int) -> float:
    """Nearest-rank percentile (explicit definition avoids tiny-sample ambiguity)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * percent / 100) - 1)], 2)


def summarize(samples: list[dict], elapsed: float) -> dict:
    durations = [sample["latency_ms"] for sample in samples]
    return {
        "requests": len(samples), "statuses": dict(Counter(str(s["status"]) for s in samples)),
        "transport_errors": sum(s["status"] == 0 for s in samples),
        "server_errors": sum(s["status"] >= 500 for s in samples),
        "latency_ms": {"p50": percentile(durations, 50), "p95": percentile(durations, 95),
                       "max": round(max(durations, default=0.0), 2)},
        "elapsed_seconds": round(elapsed, 3),
        "requests_per_second": round(len(samples) / elapsed, 2) if elapsed else 0.0,
    }


class Pilot:
    def __init__(self, args):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        self.args = args
        self.engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=20000 -c lock_timeout=10000"})
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        self.ids: dict[str, str] = {}
        self.tokens: dict[str, str] = {}
        self.checks: list[dict] = []
        self.scenarios: list[dict] = []
        self.all_samples: list[dict] = []

    def check(self, name: str, condition: bool, **evidence):
        self.checks.append({"name": name, "passed": bool(condition), **evidence})

    def prepare_database(self) -> dict:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import inspect, text
        with self.engine.connect() as connection:
            identity = connection.execute(text("SELECT current_database(), current_schema(), version()" )).one()
            if not DATABASE_PREFIX.fullmatch(identity[0]) or identity[1] != "public":
                raise PilotError("Database identity does not match the disposable pilot guard")
            object_count = connection.scalar(text("""SELECT count(*) FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
                AND c.relkind IN ('r','p','v','m','S','f')"""))
            if object_count:
                raise PilotError("The pilot refuses a nonempty database; create a new database")
            runtime = {
                "server_version": connection.scalar(text("SHOW server_version")),
                "server_version_num": connection.scalar(text("SHOW server_version_num")),
                "transaction_isolation": connection.scalar(text("SHOW transaction_isolation")),
                "max_connections": int(connection.scalar(text("SHOW max_connections"))),
                "database": identity[0], "endpoint": "literal loopback", "schema": identity[1],
                "statement_timeout_ms": 20000, "lock_timeout_ms": 10000,
            }
            locale = connection.execute(text("""SELECT pg_encoding_to_char(encoding) AS encoding,
                datlocprovider AS locale_provider, datlocale, datcollate AS lc_collate,
                datctype AS lc_ctype, datcollversion AS collation_version_recorded,
                pg_database_collation_actual_version(oid) AS collation_version_actual
                FROM pg_database WHERE datname = current_database()""")).mappings().one()
            runtime.update(dict(locale))
            runtime["locale_provider_name"] = {"b": "builtin", "c": "libc", "i": "icu"}.get(
                runtime["locale_provider"], "unknown")
            # Bound DB work for the new API process too. Name was checked with
            # the strict ASCII allowlist above; these settings affect only this
            # disposable database, never another database on the same server.
            connection.execute(text(f'ALTER DATABASE "{identity[0]}" SET statement_timeout = \'20s\''))
            connection.execute(text(f'ALTER DATABASE "{identity[0]}" SET lock_timeout = \'10s\''))
            connection.commit()
        config = Config(str(ROOT / "apps/api/alembic.ini"))
        command.upgrade(config, "head")
        with self.engine.connect() as connection:
            runtime["migration_revision"] = connection.scalar(text("SELECT version_num FROM alembic_version"))
        runtime["table_count"] = len(inspect(self.engine).get_table_names())
        return runtime

    def seed(self):
        from app.models import Consent, Direction, Document, DocumentVersion, Project, SessionToken, User
        with self.factory() as db:
            direction = Direction(slug="synthetic-pilot", name_ru="Synthetic pilot", name_en="Synthetic pilot")
            db.add(direction)
            db.flush()
            self.ids["direction"] = direction.id
            document = Document(slug="synthetic-pilot-terms", title="Synthetic fixture only",
                                scope="registration", required_roles=["mentee", "mentor"])
            db.add(document)
            db.flush()
            content = "Synthetic disposable fixture; not a real legal agreement."
            version = DocumentVersion(document_id=document.id, version="1", content=content,
                                      content_hash=hashlib.sha256(content.encode()).hexdigest())
            db.add(version)
            db.flush()
            people = [("mentor_bookings", "mentor", self.args.clients),
                      ("mentor_capacity", "mentor", 3),
                      ("mentor_project", "mentor", self.args.clients),
                      ("mentor_recurring", "mentor", self.args.clients)]
            people += [(f"mentee_{i}", "mentee", 3) for i in range(self.args.clients)]
            for key, role, capacity in people:
                user = User(email=key + "@synthetic-load.example.test", full_name="Synthetic " + key,
                            role=role, account_status="active", profile_completed=True,
                            intake_open=role == "mentor", capacity=capacity, timezone="UTC",
                            birth_date=date(2000, 1, 1), bio="Synthetic mentoring pilot fixture",
                            expertise="Python experience", direction_ids=[direction.id],
                            evidence_urls=["https://example.test/synthetic"])
                db.add(user)
                db.flush()
                self.ids[key] = user.id
                db.add(Consent(user_id=user.id, document_version_id=version.id, method="synthetic_fixture"))
                token = "synthetic-pilot-" + str(uuid4())
                self.tokens[key] = token
                digest = hmac.new(AUTH_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
                db.add(SessionToken(user_id=user.id, token_hash=digest,
                                    expires_at=datetime.now(timezone.utc) + timedelta(hours=2)))
            project = Project(owner_id=self.ids["mentor_project"], mentor_id=self.ids["mentor_project"],
                              direction_id=direction.id, title="Synthetic capacity project",
                              problem="Synthetic local pilot", description="Synthetic local pilot",
                              capacity=3, visibility_status="published")
            db.add(project)
            db.flush()
            self.ids["project"] = project.id
            db.commit()

    def headers(self, actor: str) -> dict[str, str]:
        return {"Origin": ORIGIN, "Cookie": "dc_session=" + self.tokens[actor]}

    async def request(self, client, method: str, path: str, actor: str, payload=None) -> dict:
        started = time.perf_counter()
        try:
            response = await client.request(method, "/api/v1" + path, headers=self.headers(actor), json=payload)
            try:
                body = response.json()
            except ValueError:
                body = None
            return {"status": response.status_code, "body": body, "path": path,
                    "latency_ms": (time.perf_counter() - started) * 1000, "actor": actor}
        except Exception as exc:
            return {"status": 0, "body": None, "path": path, "latency_ms": (time.perf_counter() - started) * 1000,
                    "actor": actor, "error_class": type(exc).__name__}

    async def wave(self, client, name: str, jobs: list[tuple], *, workers: int = 0) -> list[dict]:
        # Import worker dependencies before starting requests/timing. Doing a
        # first synchronous Python import inside an async worker would block
        # the client event loop and inflate every HTTP latency in this wave.
        if workers:
            from app.jobs_calendar import regenerate_rules
        gate = asyncio.Event()

        async def call(job):
            await gate.wait()
            return await self.request(client, *job)

        async def worker():
            await gate.wait()
            return await asyncio.to_thread(regenerate_rules, self.factory)

        tasks = [asyncio.create_task(call(job)) for job in jobs]
        worker_tasks = [asyncio.create_task(worker()) for _ in range(workers)]
        started = time.perf_counter()
        gate.set()
        samples = await asyncio.gather(*tasks)
        results = await asyncio.gather(*worker_tasks)
        elapsed = time.perf_counter() - started
        item = {"name": name, **summarize(samples, elapsed)}
        if workers:
            item["calendar_workers"] = results
            self.check(name + ": workers have no generation errors", all(row["errors"] == 0 for row in results))
        self.scenarios.append(item)
        self.all_samples.extend(samples)
        self.check(name + ": no transport/server errors", not item["transport_errors"] and not item["server_errors"])
        return samples

    async def setup_request(self, client, method, path, actor, payload=None, expected=201):
        sample = await self.request(client, method, path, actor, payload)
        if sample["status"] != expected or not isinstance(sample["body"], (dict, list)):
            raise PilotError(f"Synthetic setup failed at {method} {path}; status {sample['status']}")
        return sample["body"]

    async def workloads(self, base_url):
        import httpx
        from sqlalchemy import func, select
        from app.models import Application, Booking, Conversation, Participation, Slot
        from app.models_calendar import GeneratedRuleSlot
        from app.models_delivery import EmailOutbox
        from app.project_capacity import project_occupied
        from app.models import Project
        limits = httpx.Limits(max_connections=self.args.clients + 5, max_keepalive_connections=self.args.clients)
        async with httpx.AsyncClient(base_url=base_url, timeout=30, limits=limits, trust_env=False) as client:
            paths = ["/mentors?limit=20", "/projects?limit=20",
                     "/slots?mentor_id=" + self.ids["mentor_bookings"], "/bookings"]
            for round_number in range(self.args.read_rounds):
                jobs = [("GET", paths[(i + round_number) % len(paths)], f"mentee_{i}")
                        for i in range(self.args.clients)]
                samples = await self.wave(client, "reads_" + str(round_number + 1), jobs)
                self.check("reads all return 200, round " + str(round_number + 1),
                           all(row["status"] == 200 for row in samples))

            when = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=5)
            payload = {"starts_at": when.isoformat(), "timezone": "UTC"}
            slot = await self.setup_request(client, "POST", "/slots", "mentor_bookings", payload)
            samples = await self.wave(client, "competing_booking_same_slot", [
                ("POST", "/bookings", f"mentee_{i}", {"slot_id": slot["id"]})
                for i in range(self.args.clients)])
            winners = [row for row in samples if row["status"] == 201]
            self.check("same slot: exactly one successful reservation",
                       len(winners) == 1 and sum(row["status"] == 409 for row in samples) == self.args.clients - 1,
                       successful=len(winners))
            with self.factory() as db:
                count = db.scalar(select(func.count(Booking.id)).where(Booking.slot_id == slot["id"], Booking.status == "scheduled"))
                self.check("same slot: one scheduled DB row and booked slot", count == 1 and db.get(Slot, slot["id"]).status == "booked", scheduled_rows=count)
            if winners:
                winner = winners[0]
                repeats = await self.wave(client, "idempotent_booking_repeat", [
                    ("POST", "/bookings", winner["actor"], {"slot_id": slot["id"]})
                    for _ in range(self.args.clients)])
                self.check("booking retries return the same reservation", all(
                    row["status"] == 201 and isinstance(row["body"], dict) and row["body"].get("id") == winner["body"]["id"]
                    for row in repeats))
            duplicate_payload = {"starts_at": (when + timedelta(hours=2)).isoformat(), "timezone": "UTC"}
            duplicates = await self.wave(client, "competing_slot_create", [
                ("POST", "/slots", "mentor_bookings", duplicate_payload) for _ in range(self.args.clients)])
            self.check("same interval: one slot, all competitors conflict", sum(row["status"] == 201 for row in duplicates) == 1
                       and sum(row["status"] == 409 for row in duplicates) == self.args.clients - 1)

            # Different mentors cannot bypass a mentee's own overlapping meeting.
            overlap_payload = {"starts_at": (when + timedelta(days=1)).isoformat(), "timezone": "UTC"}
            overlap_slots = [await self.setup_request(client, "POST", "/slots", actor, overlap_payload)
                             for actor in ("mentor_capacity", "mentor_project")]
            overlapping = await self.wave(client, "same_mentee_competing_mentors", [
                ("POST", "/bookings", "mentee_0", {"slot_id": overlap_slots[i % 2]["id"]})
                for i in range(self.args.clients)])
            overlap_ids = [row["id"] for row in overlap_slots]
            with self.factory() as db:
                overlap_count = db.scalar(select(func.count(Booking.id)).where(Booking.slot_id.in_(overlap_ids), Booking.status == "scheduled"))
                overlap_statuses = [db.get(Slot, identifier).status for identifier in overlap_ids]
                self.check("a mentee gets one meeting across overlapping mentors", overlap_count == 1
                           and sorted(overlap_statuses) == ["available", "booked"], scheduled_rows=overlap_count)
            successful_ids = {row["body"]["id"] for row in overlapping if row["status"] == 201}
            self.check("overlap retries share one booking, other mentor conflicts", len(successful_ids) == 1
                       and any(row["status"] == 409 for row in overlapping)
                       and all(row["status"] in {201, 409} for row in overlapping))

            for actor, project_id in (("mentor_capacity", None), ("mentor_project", self.ids["project"])):
                name = "mentor_capacity" if project_id is None else "project_capacity"
                created = await self.wave(client, name + "_pending_creation", [
                    ("POST", "/applications", f"mentee_{i}", {"mentor_id": self.ids[actor],
                     "project_id": project_id, "motivation": "Synthetic concurrent local mentoring application"})
                    for i in range(self.args.clients)])
                self.check(name + ": all pending applications created", all(row["status"] == 201 for row in created))
                if not all(row["status"] == 201 for row in created):
                    continue
                accepted = await self.wave(client, name + "_competing_accepts", [
                    ("POST", "/applications/" + row["body"]["id"] + "/decision", actor, {"decision": "accepted"})
                    for row in created])
                success = sum(row["status"] == 200 for row in accepted)
                self.check(name + ": exactly capacity=3 accepted, other requests conflict", success == 3
                           and sum(row["status"] == 409 for row in accepted) == self.args.clients - 3, successful=success)
                with self.factory() as db:
                    ongoing = db.scalar(select(func.count(Participation.id)).where(Participation.mentor_id == self.ids[actor], Participation.status.in_(["active", "paused"])))
                    decided = db.scalar(select(func.count(Application.id)).where(Application.mentor_id == self.ids[actor], Application.status == "accepted"))
                    conversations = db.scalar(select(func.count(Conversation.id)).join(Application, Application.id == Conversation.application_id).where(Application.mentor_id == self.ids[actor]))
                    self.check(name + ": DB participation/application/conversation rows each equal 3",
                               ongoing == decided == conversations == 3, participations=ongoing, accepted_applications=decided, conversations=conversations)
                    if project_id:
                        occupied = project_occupied(db, db.get(Project, project_id))
                        self.check("project shared seat invariant", occupied == 3, occupied=occupied)

            starts_on = (datetime.now(timezone.utc) + timedelta(days=1)).date()
            rule = await self.setup_request(client, "POST", "/availability-rules", "mentor_recurring", {
                "weekday": starts_on.weekday(), "start_time": "09:00", "end_time": "10:00",
                "timezone": "UTC", "slot_minutes": 30, "starts_on": starts_on.isoformat(), "horizon_weeks": 4})
            rule_id, initial = rule["rule"]["id"], rule["generation"]["created"]
            generated = await self.wave(client, "recurring_regeneration_with_workers", [
                ("POST", "/availability-rules/" + rule_id + "/regenerate", "mentor_recurring")
                for _ in range(self.args.clients)], workers=4)
            self.check("repeated generation creates no additional slots", all(row["status"] == 200
                       and row["body"]["generation"]["created"] == 0 for row in generated))
            with self.factory() as db:
                links = db.scalar(select(func.count(GeneratedRuleSlot.id)).where(GeneratedRuleSlot.rule_id == rule_id))
                slot_count = db.scalar(select(func.count(Slot.id)).where(Slot.mentor_id == self.ids["mentor_recurring"], Slot.status != "cancelled"))
                distinct = db.scalar(select(func.count(func.distinct(GeneratedRuleSlot.occurrence_key))).where(GeneratedRuleSlot.rule_id == rule_id))
                self.check("recurrence: occurrence keys and active slots stay unique", initial > 0 and links == slot_count == distinct == initial,
                           initial=initial, linked=links, active_slots=slot_count, distinct_occurrences=distinct)

            await asyncio.to_thread(self.retired_rule_race, rule_id)
            with self.factory() as db:
                self.check("providers remain disabled: no email outbox rows", db.scalar(select(func.count(EmailOutbox.id))) == 0)

    def retired_rule_race(self, rule_id):
        """Deterministically retire a rule between worker read and mentor lock.

        The retiring transaction holds the same PostgreSQL mentor row lock as
        the API disable path. A probe records calls to the REAL generate_rule;
        it does not replace generation, its queries, or the locking function.
        """
        import app.jobs_calendar as jobs
        from sqlalchemy import select
        from app.models import User
        from app.models_calendar import AvailabilityRule
        from app.routers.calendar_rules import cancel_future_free
        mentor_id = self.ids["mentor_recurring"]
        attempting_lock = threading.Event()
        generated_states = []
        original_lock, original_generate = jobs._lock_users, jobs.generate_rule

        def observe_lock(db, user_ids):
            if mentor_id in user_ids:
                attempting_lock.set()
            return original_lock(db, user_ids)

        def observe_generation(db, rule, **kwargs):
            if rule.id == rule_id:
                generated_states.append(rule.active)
            return original_generate(db, rule, **kwargs)

        jobs._lock_users, jobs.generate_rule = observe_lock, observe_generation
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.factory() as retiring:
                    retiring.scalar(select(User).where(User.id == mentor_id).with_for_update())
                    future = pool.submit(jobs.regenerate_rules, self.factory)
                    if not attempting_lock.wait(10):
                        retiring.rollback()
                        raise PilotError("Rule retirement concurrency probe did not reach the mentor lock")
                    rule = retiring.get(AvailabilityRule, rule_id)
                    cancel_future_free(retiring, rule)
                    rule.active = False
                    retiring.commit()
                result = future.result(timeout=30)
            self.check("worker rechecks rule active after acquiring mentor lock", not generated_states
                       and result["processed"] == 0 and result["errors"] == 0,
                       generation_calls_after_retirement=len(generated_states), worker=result)
        finally:
            jobs._lock_users, jobs.generate_rule = original_lock, original_generate

    def run(self):
        import httpx
        started = time.perf_counter()
        runtime = self.prepare_database()
        self.seed()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        url = "http://127.0.0.1:" + str(port)
        # Runtime settings are inherited from the CLEAN child environment only.
        with tempfile.TemporaryFile(mode="w+b") as log:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                        "--port", str(port), "--no-access-log"], stdout=log, stderr=log)
            try:
                ready = False
                with httpx.Client(timeout=1, trust_env=False) as client:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise PilotError("Synthetic local API exited before readiness")
                        try:
                            ready = client.get(url + "/api/v1/ready").status_code == 200
                        except httpx.HTTPError:
                            pass
                        if ready:
                            break
                        time.sleep(0.1)
                if not ready:
                    raise PilotError("Synthetic local API readiness timed out")
                asyncio.run(self.workloads(url))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                self.engine.dispose()
        elapsed = time.perf_counter() - started
        reads = [row for row in self.all_samples if row["path"].split("?")[0] in {"/mentors", "/projects", "/slots", "/bookings"}
                 and row["status"] == 200]
        source_files = ["scripts/verification/postgres_load.py", "apps/api/app/jobs_calendar.py",
                        "apps/api/app/routers/bookings.py", "apps/api/app/routers/projects.py",
                        "apps/api/app/routers/calendar_rules.py", "apps/api/app/models.py"]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "Synthetic local PostgreSQL + HTTP API; not production or cloud capacity",
            "authentication": "Synthetic persisted sessions; normal API authentication dependencies",
            "percentile_method": "nearest rank", "concurrent_http_clients": self.args.clients,
            "read_rounds": self.args.read_rounds, "calendar_workers": 4,
            "fixture_users": self.args.clients + 4, "runtime": runtime,
            "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                              for name in source_files},
            "aggregate": summarize(self.all_samples, sum(s["elapsed_seconds"] for s in self.scenarios)),
            "read_latency_ms": {"p50": percentile([s["latency_ms"] for s in reads], 50),
                                "p95": percentile([s["latency_ms"] for s in reads], 95),
                                "max": round(max((s["latency_ms"] for s in reads), default=0), 2)},
            "scenarios": self.scenarios, "invariants": self.checks,
            "passed": all(check["passed"] for check in self.checks),
            "total_elapsed_seconds": round(elapsed, 3),
            "limitations": ["Single local Uvicorn process and one local PostgreSQL instance",
                            "Small synthetic dataset; latency includes client, network and DB work",
                            "No real mail, OAuth, private storage, or Vercel execution measured",
                            "Authentication challenges/MFA and browser UI are outside this pilot"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-file", type=Path)
    parser.add_argument("--clients", type=int, default=20)
    parser.add_argument("--read-rounds", type=int, default=5)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--_execute", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 4 <= args.clients <= 30 or not 1 <= args.read_rounds <= 20:
        parser.error("clients must be 4..30 and read-rounds 1..20")
    report_path = args.report.resolve()
    try:
        if not args._execute:
            if not args.database_url_file:
                parser.error("--database-url-file is required")
            value = args.database_url_file.read_text(encoding="utf-8-sig").strip()
            if len(value) > 4096 or "\n" in value:
                raise PilotError("URL file must contain one connection URL")
            database_url = validate_database_url(value)
            # Reexec from a fresh temporary directory, before importing app.config.
            # This isolates both environment variables and workspace dotenv files.
            with tempfile.TemporaryDirectory(prefix="danaconnect-pg-pilot-") as directory:
                return subprocess.call([sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
                    "--_execute", "--clients", str(args.clients), "--read-rounds", str(args.read_rounds),
                    "--report", str(report_path)], cwd=directory, env=clean_environment(database_url))
        if os.environ.get("DC_SYNTHETIC_PILOT_CHILD") != "1" or not Path.cwd().name.startswith("danaconnect-pg-pilot-"):
            raise PilotError("The internal child mode must run through the isolated parent launcher")
        validate_database_url(os.environ.get("DATABASE_URL", ""))
        report = Pilot(args).run()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "requests": report["aggregate"]["requests"],
                          "checks": len(report["invariants"]), "report": str(report_path)}, ensure_ascii=False))
        return 0 if report["passed"] else 1
    except PilotError as exc:
        print("Pilot refused/failed: " + str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        # Exception text can contain connection details. Emit only its class.
        print("Pilot failed: " + type(exc).__name__ + "; no credentials printed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
