"""Full-app fixtures use temporary SQLite and real OTP/session dependencies."""
from contextlib import ExitStack
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import get_db
from app.main import app
from app.models import Base, Consent, Direction, Document, DocumentVersion, User
from app.routers.identity import _ip_requests


class IntegratedAPI:
    origin = "http://localhost:3000"

    def __init__(self, factory, ids, stack):
        self.factory, self.ids, self.stack = factory, ids, stack
        self.clients = {}

    def client(self, who="anonymous"):
        if who not in self.clients:
            self.clients[who] = self.stack.enter_context(TestClient(app))
            if who != "anonymous":
                self.login(who, f"{who}@example.test")
        return self.clients[who]

    def login(self, who, email):
        client = self.clients.get(who)
        if client is None:
            client = self.stack.enter_context(TestClient(app))
            self.clients[who] = client
        requested = client.post("/api/v1/auth/request-code", json={"email": email}, headers={"origin": self.origin})
        assert requested.status_code == 200, requested.text
        verified = client.post("/api/v1/auth/verify-code", json={"challenge_id": requested.json()["challenge_id"], "code": requested.json()["debug_code"]}, headers={"origin": self.origin})
        assert verified.status_code == 200, verified.text
        self.ids[who] = verified.json()["id"]
        return verified

    def call(self, method, path, who="anonymous", **kwargs):
        return self.client(who).request(method, "/api/v1" + path, headers={"origin": self.origin}, **kwargs)

    def profile(self, role="mentee", **changes):
        payload = {"full_name": "Sample Person", "role": role, "timezone": "Asia/Oral", "city": "Oral", "birth_date": "2000-01-01", "bio": "A meaningful sample biography", "expertise": "Python mentoring experience" if role == "mentor" else "", "evidence_urls": ["https://example.test/evidence"] if role == "mentor" else [], "direction_ids": [self.ids["direction"]], "capacity": 3}
        payload.update(changes)
        return payload


@pytest.fixture
def integrated_api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "auth_debug_code", True)
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "auth_secret", "isolated-test-secret-never-used-for-deployment")
    monkeypatch.setattr(settings, "trusted_origins", [IntegratedAPI.origin])
    _ip_requests.clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'integrated.db'}", connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    ids = {}
    with factory() as db:
        direction = Direction(slug="ai", name_ru="ИИ", name_kk="ЖИ", name_en="AI")
        db.add(direction)
        db.flush()
        ids["direction"] = direction.id
        for key, role in (("admin", "admin"), ("mentor", "mentor"), ("mentee", "mentee"), ("stranger", "mentee")):
            user = User(email=f"{key}@example.test", full_name=f"Sample {key}", role=role, account_status="active", profile_completed=True, intake_open=role == "mentor", direction_ids=[direction.id], capacity=3, city="Oral", birth_date=date(2000, 1, 1), bio="A meaningful sample biography", expertise="Python mentoring experience", evidence_urls=["https://example.test/private-evidence"], phone="PRIVATE-PHONE")
            db.add(user)
            db.flush()
            ids[key] = user.id
        document = Document(slug="terms", title="Sample terms", scope="registration", required_roles=["mentee", "mentor"])
        db.add(document)
        db.flush()
        version = DocumentVersion(document_id=document.id, version="1", content="Sample document content for development only", content_hash="a" * 64)
        db.add(version)
        db.flush()
        ids.update(document=document.id, version=version.id)
        db.add_all([Consent(user_id=ids[key], document_version_id=version.id) for key in ("mentor", "mentee", "stranger")])
        db.commit()

    def isolated_db():
        with factory() as db:
            yield db

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = isolated_db
    try:
        with ExitStack() as stack:
            yield IntegratedAPI(factory, ids, stack)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()
        _ip_requests.clear()
