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
                      ("mentor_recurring", "mentor", self.args.clients),
                      ("mentor_offer_a", "mentor", self.args.clients),
                      ("mentor_offer_b", "mentor", self.args.clients)]
            people += [(f"mentee_{i}", "mentee", 3) for i in range(self.args.clients)]
            # Exercise sorted locking when BOTH competing mentor IDs sort before
            # the shared owner. Random UUIDs could silently miss that lock order.
            fixed_ids = {"mentor_offer_a": "00000000-0000-4000-8000-000000000001",
                         "mentor_offer_b": "00000000-0000-4000-8000-000000000002",
                         "mentee_0": "ffffffff-ffff-4fff-8fff-fffffffffff0"}
            for key, role, capacity in people:
                user = User(id=fixed_ids.get(key, str(uuid4())), email=key + "@synthetic-load.example.test", full_name="Synthetic " + key,
                            role=role, account_status="active", profile_completed=True,
                            intake_open=role == "mentor", capacity=capacity, timezone="UTC",
                            city="Synthetic city", organization="Synthetic workplace", phone="+7 700 000 00 00",
                            mentor_commitment=role == "mentor", mentor_commitment_accepted_at=datetime.now(timezone.utc) if role == "mentor" else None,
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
            idea = Project(owner_id=self.ids["mentee_0"], direction_id=direction.id,
                           title="Synthetic competing mentor offer idea",
                           problem="Synthetic mentor selection concurrency test",
                           description="A mentee idea with two independently offered mentors",
                           capacity=2, visibility_status="published")
            db.add(idea)
            db.flush()
            self.ids["mentor_offer_idea"] = idea.id
            for key in ("mentor_offer_withdraw_idea", "mentor_offer_fresh_accept_idea", "mentor_offer_fresh_create_idea"):
                idea = Project(owner_id=self.ids["mentee_0"], direction_id=direction.id,
                               title="Synthetic " + key, problem="Synthetic bounded lock regression",
                               description="A synthetic idea sharing the same mentee owner",
                               capacity=2, visibility_status="published")
                db.add(idea)
                db.flush()
                self.ids[key] = idea.id
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

    def blocking_graph(self):
        """Read only this already-guarded disposable database's lock wait graph."""
        from sqlalchemy import text
        with self.engine.connect() as connection:
            return list(connection.execute(text("""SELECT pid, pg_blocking_pids(pid)
                FROM pg_stat_activity WHERE datname=current_database()
                AND cardinality(pg_blocking_pids(pid)) > 0""")))

    async def application_gate_race(self, client, name, application_id, first_job, second_job):
        """Force API transactions to overlap before releasing one fixture row.

        An external Application row lock pauses the first request after it
        reaches its write. The second reaches the first request's users (or,
        with the old withdrawal order, the same Application gate). Releasing
        the gate exposes the old user/FK/Application lock cycles reliably.
        Each observation is bounded to four seconds, below lock_timeout=10s.
        """
        from sqlalchemy import select, text
        from app.models import Application

        async def observe_blocked_by(identifiers):
            deadline = asyncio.get_running_loop().time() + 4
            while asyncio.get_running_loop().time() < deadline:
                graph = await asyncio.to_thread(self.blocking_graph)
                matched = [pid for pid, blockers in graph if set(blockers) & identifiers]
                if matched:
                    return matched[0]
                await asyncio.sleep(0.025)
            return None

        tasks = []
        started = time.perf_counter()
        with self.factory() as gate:
            gate.scalar(select(Application).where(Application.id == application_id).with_for_update())
            gate_pid = gate.scalar(text("SELECT pg_backend_pid()"))
            try:
                tasks.append(asyncio.create_task(self.request(client, *first_job)))
                first_pid = await observe_blocked_by({gate_pid})
                self.check(name + ": first request reached the Application gate", first_pid is not None)
                tasks.append(asyncio.create_task(self.request(client, *second_job)))
                # Exclude the first request itself when observing a second waiter.
                deadline = asyncio.get_running_loop().time() + 4
                second_pid = None
                while asyncio.get_running_loop().time() < deadline:
                    graph = await asyncio.to_thread(self.blocking_graph)
                    second_pid = next((pid for pid, blockers in graph
                        if pid != first_pid and set(blockers) & {gate_pid, first_pid}), None)
                    if second_pid is not None:
                        break
                    await asyncio.sleep(0.025)
                self.check(name + ": second request overlapped the first transaction", second_pid is not None)
            finally:
                gate.rollback()
        samples = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - started
        item = {"name": name, "overlap": "Application gate + observed PostgreSQL blocking graph",
                **summarize(samples, elapsed)}
        self.scenarios.append(item)
        self.all_samples.extend(samples)
        self.check(name + ": no transport/server errors", not item["transport_errors"] and not item["server_errors"])
        return samples

    async def workloads(self, base_url):
        import httpx
        from sqlalchemy import func, select
        from app.models import Application, Booking, Conversation, ConversationMember, Participation, ProjectMember, Slot
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

            # Distinct mentors and their shared mentee lock in sorted order. Two
            # simultaneous owner decisions must assign only one of the offers.
            idea_id = self.ids["mentor_offer_idea"]
            offers = [await self.setup_request(client, "POST", f"/projects/{idea_id}/mentor-offers", actor,
                      {"motivation": "Synthetic mentor offer for a mentee idea"})
                      for actor in ("mentor_offer_a", "mentor_offer_b")]
            accepted = await self.wave(client, "competing_mentor_offer_owner_accepts", [
                ("POST", "/applications/" + item["id"] + "/decision", "mentee_0", {"decision": "accepted"})
                for item in offers])
            self.check("mentor offers: exactly one owner acceptance, other conflicts",
                       sorted(row["status"] for row in accepted) == [200, 409])
            with self.factory() as db:
                rows = list(db.scalars(select(Application).where(Application.id.in_([item["id"] for item in offers]))))
                participation_rows = list(db.scalars(select(Participation).where(Participation.project_id == idea_id)))
                conversations = list(db.scalars(select(Conversation).join(Application,
                    Application.id == Conversation.application_id).where(Application.project_id == idea_id)))
                winner = next((row for row in rows if row.status == "accepted"), None)
                loser = next((row for row in rows if row.status == "rejected"), None)
                idea = db.get(Project, idea_id)
                self.check("mentor offers: one accepted, competing offer closed",
                           winner is not None and loser is not None and loser.rejection_reason == "project_closed")
                self.check("mentor offers: one participation and one conversation",
                           len(participation_rows) == len(conversations) == 1,
                           participations=len(participation_rows), conversations=len(conversations))
                self.check("mentor offers: idea and participation assign the accepted mentor",
                           winner is not None and len(participation_rows) == 1
                           and idea.mentor_id == participation_rows[0].mentor_id == winner.mentor_id
                           and participation_rows[0].mentee_id == idea.owner_id)
                if winner is not None and len(conversations) == 1:
                    members = set(db.scalars(select(ConversationMember.user_id).where(
                        ConversationMember.conversation_id == conversations[0].id)))
                    team = set(db.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == idea_id)))
                    self.check("mentor offers: only the accepted parties join chat and project",
                               members == team == {winner.mentor_id, winner.mentee_id})

            self.check("mentor lock order: competing mentors sort before shared owner",
                       self.ids["mentor_offer_a"] < self.ids["mentor_offer_b"] < self.ids["mentee_0"])
            withdraw_idea = self.ids["mentor_offer_withdraw_idea"]
            withdraw_offer = await self.setup_request(client, "POST", f"/projects/{withdraw_idea}/mentor-offers",
                "mentor_offer_a", {"motivation": "Synthetic withdrawal and acceptance race"})
            races = await self.application_gate_race(client, "mentor_offer_accept_vs_withdraw", withdraw_offer["id"],
                ("POST", f"/applications/{withdraw_offer['id']}/withdraw", "mentor_offer_a"),
                ("POST", f"/applications/{withdraw_offer['id']}/decision", "mentee_0", {"decision": "accepted"}))
            self.check("accept/withdraw: exactly one action succeeds", sorted(row["status"] for row in races) == [200, 409])
            with self.factory() as db:
                application = db.get(Application, withdraw_offer["id"])
                count = db.scalar(select(func.count(Participation.id)).where(Participation.project_id == withdraw_idea))
                conversations = db.scalar(select(func.count(Conversation.id)).where(Conversation.application_id == application.id))
                members = db.scalar(select(func.count(ProjectMember.id)).where(ProjectMember.project_id == withdraw_idea))
                self.check("accept/withdraw: status and matching records agree",
                           (application.status == "withdrawn" and count == conversations == members == 0)
                           or (application.status == "accepted" and count == conversations == 1 and members == 2),
                           application_status=application.status, participations=count, conversations=conversations)

            # The fresh offer targets a second idea by the SAME owner. Accepting
            # the first idea closes the competing mentor's older pending offer,
            # which inserts a notification FK while that mentor awaits the owner.
            accept_idea, fresh_idea = self.ids["mentor_offer_fresh_accept_idea"], self.ids["mentor_offer_fresh_create_idea"]
            accepted_offer = await self.setup_request(client, "POST", f"/projects/{accept_idea}/mentor-offers",
                "mentor_offer_a", {"motivation": "Synthetic mentor selection with concurrent recruitment"})
            competing_offer = await self.setup_request(client, "POST", f"/projects/{accept_idea}/mentor-offers",
                "mentor_offer_b", {"motivation": "Synthetic competing mentor offer to close"})
            fresh_races = await self.application_gate_race(client, "mentor_offer_accept_vs_fresh_offer", accepted_offer["id"],
                ("POST", f"/applications/{accepted_offer['id']}/decision", "mentee_0", {"decision": "accepted"}),
                ("POST", f"/projects/{fresh_idea}/mentor-offers", "mentor_offer_b",
                 {"motivation": "Synthetic fresh offer sharing the idea owner"}))
            self.check("accept/fresh offer: both independent actions finish", [row["status"] for row in fresh_races] == [200, 201])
            with self.factory() as db:
                winner, loser = db.get(Application, accepted_offer["id"]), db.get(Application, competing_offer["id"])
                fresh_rows = list(db.scalars(select(Application).where(Application.project_id == fresh_idea)))
                accepted_count = db.scalar(select(func.count(Participation.id)).where(Participation.project_id == accept_idea))
                conversations = db.scalar(select(func.count(Conversation.id)).where(Conversation.application_id == winner.id))
                self.check("accept/fresh offer: chosen idea has one accepted mentor and closed competitor",
                           winner.status == "accepted" and loser.status == "rejected" and loser.rejection_reason == "project_closed"
                           and db.get(Project, accept_idea).mentor_id == self.ids["mentor_offer_a"]
                           and accepted_count == conversations == 1)
                self.check("accept/fresh offer: other idea retains exactly one pending offer without matching",
                           len(fresh_rows) == 1 and fresh_rows[0].status == "pending"
                           and fresh_rows[0].mentor_id == self.ids["mentor_offer_b"]
                           and db.get(Project, fresh_idea).mentor_id is None
                           and db.scalar(select(func.count(Participation.id)).where(Participation.project_id == fresh_idea)) == 0)

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
            "fixture_users": self.args.clients + 6, "runtime": runtime,
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
