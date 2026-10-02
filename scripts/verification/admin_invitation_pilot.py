"""Synthetic PostgreSQL invitation races; refuses remote or nonempty databases.

Uses the PostgreSQL pilot's isolated launcher and identity guards. No real email,
OAuth, provider worker, or production credentials are loaded.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, parse_qs

from postgres_load import Pilot, PilotError, ROOT, ORIGIN, clean_environment, validate_database_url


def execute(args):
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from app.auth import secret_hash, totp_code, utcnow
    from app.config import settings
    from app.database import get_db
    from app.delivery import decrypt_text, encrypt_text
    from app.main import app
    from app.models import AuthChallenge, SessionToken, User
    from app.models_admin_invitations import AdminInvitation, AdminInvitationChallenge
    from app.models_delivery import AdminCredential, EmailOutbox, SessionAssurance

    pilot = Pilot(argparse.Namespace(clients=args.clients))
    runtime = pilot.prepare_database()
    settings.auth_debug_code = True
    settings.email_provider = "smtp"
    settings.email_from = "synthetic-sender@example.test"
    settings.smtp_host = "smtp.example.invalid"
    settings.smtp_username = ""
    settings.smtp_password = ""
    token = secrets.token_urlsafe(48)
    with pilot.factory() as db:
        owner = User(email="synthetic-owner@example.test", role="admin", account_status="active",
                     full_name="Synthetic owner", profile_completed=True)
        db.add(owner)
        db.flush()
        db.add(AdminCredential(user_id=owner.id, encrypted_totp_secret=encrypt_text("JBSWY3DPEHPK3PXP")))
        session = SessionToken(user_id=owner.id, token_hash=secret_hash(token),
                               expires_at=utcnow() + timedelta(hours=1))
        db.add(session)
        db.flush()
        db.add(SessionAssurance(session_id=session.id))
        db.commit()

    def isolated_db():
        with pilot.factory() as db:
            yield db

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = isolated_db
    checks, waves = [], []

    def check(name, passed):
        checks.append({"name": name, "passed": bool(passed)})

    def call(path, payload, admin=False, method="POST"):
        with TestClient(app) as client:
            if admin:
                client.cookies.set("dc_session", token)
            return client.request(method, "/api/v1" + path, json=payload, headers={"origin": ORIGIN})

    def wave(name, path, payload, admin=False):
        with ThreadPoolExecutor(max_workers=args.clients) as executor:
            replies = list(executor.map(lambda _: call(path, payload, admin), range(args.clients)))
        statuses = dict(Counter(str(r.status_code) for r in replies))
        waves.append({"name": name, "requests": len(replies), "statuses": statuses})
        check(name + " has no server errors", all(r.status_code < 500 for r in replies))
        winners = [r for r in replies if r.status_code in {200, 201}]
        check(name + " has exactly one winner", len(winners) == 1)
        if len(winners) != 1:
            raise PilotError("Invitation race did not have exactly one winner; response bodies suppressed")
        return winners[0]

    try:
        created = wave("create invitation", "/admin/invitations",
                       {"email": "synthetic-invitee@example.test", "full_name": "Synthetic invitee", "locale": "ru"}, True)
        check("creation never exposes a bearer token", "token" not in created.text and "totp" not in created.text)
        with pilot.factory() as db:
            rows = list(db.scalars(select(EmailOutbox)))
            check("one encrypted invitation email", len(rows) == 1 and rows[0].status == "pending")
            payload = json.loads(decrypt_text(rows[0].encrypted_payload))
            links = [word for word in payload["text"].split() if "#token=" in word]
            if len(links) != 1:
                raise PilotError("Synthetic invitation template did not contain one invitation link")
            invitation_token = parse_qs(urlsplit(links[0]).fragment)["token"][0]
            check("invitee has no account before proof", db.scalar(select(func.count(User.id)).where(User.email == "synthetic-invitee@example.test")) == 0)
        requested = wave("request invitation OTP", "/auth/admin-invitations/request-code", {"token": invitation_token})
        challenge = requested.json()
        verified = wave("consume invitation OTP", "/auth/admin-invitations/verify-code",
                        {"token": invitation_token, "challenge_id": challenge["challenge_id"], "code": challenge["debug_code"]})
        check("email proof does not issue a session", "set-cookie" not in verified.headers)
        enrollment = verified.json()
        check("QR generated locally", enrollment["qr_data_url"].startswith("data:image/svg+xml;base64,"))
        accepted = wave("consume MFA enrollment", "/auth/admin-invitations/accept",
                        {"enrollment_token": enrollment["enrollment_token"], "code": totp_code(enrollment["manual_entry_key"])})
        check("MFA acceptance issues administrator session", accepted.json().get("role") == "admin" and "httponly" in accepted.headers.get("set-cookie", "").lower())
        with pilot.factory() as db:
            invitee = db.scalar(select(User).where(User.email == "synthetic-invitee@example.test"))
            check("one invitee account", db.scalar(select(func.count(User.id)).where(User.email == "synthetic-invitee@example.test")) == 1)
            check("one active MFA credential", db.scalar(select(func.count(AdminCredential.id)).where(AdminCredential.user_id == invitee.id, AdminCredential.active.is_(True))) == 1)
            sessions = list(db.scalars(select(SessionToken).where(SessionToken.user_id == invitee.id)))
            check("one assured invitee session", len(sessions) == 1 and db.scalar(select(SessionAssurance.id).where(SessionAssurance.session_id == sessions[0].id)) is not None)
        # A second, distinct invite tests revocation racing with MFA acceptance.
        # Reset only the disposable process IP quota between independent scenarios.
        from app.routers.identity import _ip_requests
        _ip_requests.clear()
        race_email = "synthetic-race-invitee@example.test"
        race_created = call("/admin/invitations", {"email": race_email, "full_name": "Synthetic race invitee", "locale": "en"}, True)
        if race_created.status_code != 201:
            raise PilotError("Revocation race setup could not create its synthetic invitation")
        race_id = race_created.json()["id"]
        with pilot.factory() as db:
            row = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "admin-invitation:" + race_id))
            text = json.loads(decrypt_text(row.encrypted_payload))["text"]
            link = next(word for word in text.split() if "#token=" in word)
            race_token = parse_qs(urlsplit(link).fragment)["token"][0]
        race_challenge = call("/auth/admin-invitations/request-code", {"token": race_token}).json()
        race_enrollment = call("/auth/admin-invitations/verify-code", {"token": race_token,
                               "challenge_id": race_challenge["challenge_id"], "code": race_challenge["debug_code"]}).json()
        race_payload = {"enrollment_token": race_enrollment["enrollment_token"],
                        "code": totp_code(race_enrollment["manual_entry_key"])}
        def race_request(index):
            if index % 2:
                return ("revoke", call("/admin/invitations/" + race_id, None, True, "DELETE"))
            return ("accept", call("/auth/admin-invitations/accept", race_payload))
        with ThreadPoolExecutor(max_workers=args.clients) as executor:
            results = list(executor.map(race_request, range(args.clients)))
        waves.append({"name": "revoke versus accept", "requests": len(results),
                      "statuses": dict(Counter(kind + ":" + str(reply.status_code) for kind, reply in results))})
        check("revocation race has no server errors", all(reply.status_code < 500 for _,reply in results))
        accept_winners = sum(kind == "accept" and reply.status_code == 200 for kind,reply in results)
        check("revocation race has at most one accepted account", accept_winners <= 1)
        with pilot.factory() as db:
            invitation = db.get(AdminInvitation, race_id)
            accounts = db.scalar(select(func.count(User.id)).where(User.email == race_email))
            check("revocation race final state is serialized", (invitation.status == "accepted" and accounts == accept_winners == 1)
                  or (invitation.status == "revoked" and accounts == accept_winners == 0))
            check("revocation race destroys pending enrollment secrets", invitation.encrypted_seed == "" and invitation.proof_hash is None)
            row = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "admin-invitation:" + race_id))
            check("revocation race erases unsent invitation payload", row.status == "failed" and row.encrypted_payload == "")
        _ip_requests.clear()
        shared_email = "synthetic-shared-quota@example.test"
        shared_created = call("/admin/invitations", {"email": shared_email, "full_name": "Synthetic shared quota", "locale": "ru"}, True)
        if shared_created.status_code != 201:
            raise PilotError("Shared OTP race could not create its synthetic invitation")
        with pilot.factory() as db:
            row = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "admin-invitation:" + shared_created.json()["id"]))
            link = next(word for word in json.loads(decrypt_text(row.encrypted_payload))["text"].split() if "#token=" in word)
            shared_token = parse_qs(urlsplit(link).fragment)["token"][0]
        def quota_request(index):
            if index % 2:
                return ("ordinary", call("/auth/request-code", {"email": shared_email}))
            return ("invitation", call("/auth/admin-invitations/request-code", {"token": shared_token}))
        with ThreadPoolExecutor(max_workers=args.clients) as executor:
            results = list(executor.map(quota_request, range(args.clients)))
        waves.append({"name": "shared OTP quota", "requests": len(results),
                      "statuses": dict(Counter(kind + ":" + str(reply.status_code) for kind,reply in results))})
        check("shared OTP quota has one winner", sum(reply.status_code == 200 for _,reply in results) == 1)
        check("shared OTP competitors all hit persisted rate limit", sum(reply.status_code == 429 for _,reply in results) == args.clients - 1)
        with pilot.factory() as db:
            count = sum(db.scalar(select(func.count(model.id)).where(model.email == shared_email))
                        for model in (AuthChallenge, AdminInvitationChallenge))
            check("shared OTP persisted only one challenge across both routes", count == 1)
        # No provider dispatcher runs anywhere in this pilot.
        report = {"generated_at": utcnow().isoformat(), "scope": "Synthetic PostgreSQL invitation HTTP races with TestClient; no real email",
                  "runtime": runtime, "concurrent_clients": args.clients, "waves": waves, "setup_requests": 4, "checks": checks,
                  "passed": all(c["passed"] for c in checks),
                  "limitations": ["SMTP delivery and inbox receipt are not measured", "Synthetic owner session is pre-provisioned with MFA assurance", "Browser UI is checked separately"]}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "checks": len(checks), "requests": sum(w["requests"] for w in waves)}))
        return 0 if report["passed"] else 1
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        pilot.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-file", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--clients", type=int, default=20)
    parser.add_argument("--_execute", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.report = args.report.resolve()
    if not 4 <= args.clients <= 30:
        parser.error("clients must be 4..30")
    try:
        if not args._execute:
            if not args.database_url_file:
                parser.error("database-url-file is required")
            value = args.database_url_file.read_text(encoding="utf-8-sig").strip()
            database_url = validate_database_url(value)
            with tempfile.TemporaryDirectory(prefix="danaconnect-pg-pilot-") as directory:
                return subprocess.call([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--_execute",
                                        "--clients", str(args.clients), "--report", str(args.report)],
                                       cwd=directory, env=clean_environment(database_url))
        if os.environ.get("DC_SYNTHETIC_PILOT_CHILD") != "1" or not Path.cwd().name.startswith("danaconnect-pg-pilot-"):
            raise PilotError("Internal mode must use the isolated launcher")
        validate_database_url(os.environ.get("DATABASE_URL", ""))
        return execute(args)
    except PilotError as exc:
        print("Synthetic invitation pilot refused/failed: " + str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print("Synthetic invitation pilot failed: " + type(exc).__name__ + "; response bodies and credentials suppressed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
