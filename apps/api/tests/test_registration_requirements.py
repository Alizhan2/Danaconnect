"""Registration consent configuration: never admit users through missing terms."""
from datetime import timedelta

import pytest
from sqlalchemy import delete

from app.auth import has_current_consents, required_document_state, utcnow
from app.config import settings
from app.models import Consent, Document, DocumentVersion, User


def clear_documents(api):
    with api.factory() as db:
        db.execute(delete(Consent))
        db.execute(delete(DocumentVersion))
        db.execute(delete(Document))
        db.commit()


def add_document(api, **changes):
    with api.factory() as db:
        document = Document(slug="sample-required", title="Sample required terms",
                            scope="registration", required_roles=["mentee", "mentor"])
        for name, value in changes.items():
            setattr(document, name, value)
        db.add(document)
        db.commit()
        return document.id


def publish(api, document_id, version="1"):
    with api.factory() as db:
        item = DocumentVersion(document_id=document_id, version=version,
                               content="Isolated sample terms, not production legal text",
                               content_hash="a" * 64,
                               published_at=utcnow() + timedelta(seconds=int(version)))
        db.add(item)
        db.commit()
        return item.id


@pytest.mark.parametrize("role", ["mentee", "mentor", "unchosen"])
def test_production_registration_without_documents_is_not_configured(integrated_api, monkeypatch, role):
    api = integrated_api
    clear_documents(api)
    monkeypatch.setattr(settings, "environment", "production")
    with api.factory() as db:
        user = db.get(User, api.ids["mentee"])
        user.role = role
        assert required_document_state(db, user) == (False, [])
        assert has_current_consents(db, user) is False


@pytest.mark.parametrize("scope, expected", [
    ("registration", False), ("showcase", False), ("intake", True),
    ("private_project", True),
])
def test_production_empty_scope_requirements(integrated_api, monkeypatch, scope, expected):
    api = integrated_api
    clear_documents(api)
    monkeypatch.setattr(settings, "environment", "production")
    with api.factory() as db:
        user = db.get(User, api.ids["mentee"])
        assert required_document_state(db, user, scopes=(scope,)) == (expected, [])
        assert has_current_consents(db, user, scopes=(scope,)) is expected


@pytest.mark.parametrize("environment", ["test", "production"])
def test_unpublished_applicable_document_blocks_consent(integrated_api, monkeypatch, environment):
    api = integrated_api
    add_document(api, slug="unpublished")
    monkeypatch.setattr(settings, "environment", environment)
    with api.factory() as db:
        user = db.get(User, api.ids["mentee"])
        configured, versions = required_document_state(db, user)
        assert configured is False
        assert {version.id for version in versions} == {api.ids["version"]}
        assert has_current_consents(db, user) is False


@pytest.mark.parametrize("changes, blocks", [
    ({"active": False}, False),
    ({"required_roles": ["mentor"]}, False),
    ({"required_roles": []}, True),
    ({"direction_id": "other-direction"}, False),
    ({"scope": "private_project"}, False),
    ({"scope": "intake"}, True),
])
def test_only_applicable_active_documents_are_required(integrated_api, changes, blocks):
    api = integrated_api
    if changes.get("direction_id"):
        from app.models import Direction
        with api.factory() as db:
            db.add(Direction(id="other-direction", slug="other", name_ru="Other"))
            db.commit()
    add_document(api, **changes)
    with api.factory() as db:
        user = db.get(User, api.ids["mentee"])
        assert required_document_state(db, user)[0] is (not blocks)
        assert has_current_consents(db, user) is (not blocks)


def test_nonapplicable_registration_document_does_not_configure_production(integrated_api, monkeypatch):
    api = integrated_api
    clear_documents(api)
    publish(api, add_document(api, required_roles=["mentor"]))
    monkeypatch.setattr(settings, "environment", "production")
    with api.factory() as db:
        assert required_document_state(db, db.get(User, api.ids["mentee"])) == (False, [])
        assert required_document_state(db, db.get(User, api.ids["mentor"]))[0] is True


def test_admin_can_publish_first_terms_without_participant_consents(integrated_api, monkeypatch):
    api = integrated_api
    clear_documents(api)
    monkeypatch.setattr(settings, "environment", "production")
    with api.factory() as db:
        admin = db.get(User, api.ids["admin"])
        assert required_document_state(db, admin) == (True, [])
        assert has_current_consents(db, admin) is True


def test_requirements_endpoint_requires_login_and_tracks_latest_acceptance(integrated_api):
    api = integrated_api
    assert api.call("GET", "/me/registration-requirements").status_code == 401
    expected = {"documents_configured": True,
                "required_version_ids": [api.ids["version"]], "unaccepted_version_ids": []}
    assert api.call("GET", "/me/registration-requirements", "mentee").json() == expected
    latest = publish(api, api.ids["document"], "2")
    expected.update(required_version_ids=[latest], unaccepted_version_ids=[latest])
    assert api.call("GET", "/me/registration-requirements", "mentee").json() == expected
    assert api.call("POST", f"/documents/{latest}/consent", "mentee").status_code == 200
    expected["unaccepted_version_ids"] = []
    assert api.call("GET", "/me/registration-requirements", "mentee").json() == expected


@pytest.mark.parametrize("unpublished", [False, True])
def test_registration_distinguishes_unconfigured_from_missing_consent(integrated_api, monkeypatch, unpublished):
    api = integrated_api
    api.login("newcomer", "newcomer@example.test")
    assert api.call("PUT", "/me/profile", "newcomer", json=api.profile()).status_code == 200
    clear_documents(api)
    if unpublished:
        add_document(api)
    monkeypatch.setattr(settings, "environment", "production")
    requirements = api.call("GET", "/me/registration-requirements", "newcomer")
    assert requirements.status_code == 200
    assert requirements.json() == {"documents_configured": False,
                                   "required_version_ids": [], "unaccepted_version_ids": []}
    blocked = api.call("POST", "/me/submit-registration", "newcomer")
    assert blocked.status_code == 503
    assert "ещё не опубликованы" in blocked.json()["detail"]
    with api.factory() as db:
        assert db.get(User, api.ids["newcomer"]).account_status == "draft"


def test_configured_registration_requires_acceptance_then_submits(integrated_api):
    api = integrated_api
    api.login("newcomer", "newcomer@example.test")
    api.call("PUT", "/me/profile", "newcomer", json=api.profile())
    response = api.call("GET", "/me/registration-requirements", "newcomer")
    assert response.status_code == 200
    assert response.json() == {"documents_configured": True,
                               "required_version_ids": [api.ids["version"]],
                               "unaccepted_version_ids": [api.ids["version"]]}
    assert api.call("POST", "/me/submit-registration", "newcomer").status_code == 409
    assert api.call("POST", f"/documents/{api.ids['version']}/consent", "newcomer").status_code == 200
    submitted = api.call("POST", "/me/submit-registration", "newcomer")
    assert submitted.status_code == 200
    assert submitted.json()["account_status"] == "pending"
