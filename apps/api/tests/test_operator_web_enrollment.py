from datetime import timedelta

import pytest
from sqlalchemy import select

from app.admin_bootstrap import authorize_web_enrollment
from app.auth import aware
from app.models import User, utcnow
from app.models_delivery import AdminCredential


def test_operator_can_prepare_first_login_without_an_enrollment_file(integrated_api):
    with integrated_api.factory() as db:
        start = utcnow()
        identifier = authorize_web_enrollment(db, email="new-admin@example.test", name="New Admin")
        credential = db.scalar(select(AdminCredential).where(AdminCredential.user_id == identifier))
        assert db.get(User, identifier).role == "admin"
        assert not credential.active and credential.encrypted_totp_secret == ""
        assert start + timedelta(days=7) <= aware(credential.enrollment_expires_at) <= utcnow() + timedelta(days=7)


@pytest.mark.parametrize(("active", "step"), [(False, -1), (True, 1)])
def test_first_time_setup_cannot_replace_disabled_or_used_authenticator(integrated_api, active, step):
    with integrated_api.factory() as db:
        identifier = integrated_api.ids["admin"]
        db.add(AdminCredential(user_id=identifier, encrypted_totp_secret="existing",
                               active=active, last_used_step=step))
        db.commit()
        with pytest.raises(ValueError, match="First-time setup is unavailable"):
            authorize_web_enrollment(db, email=db.get(User, identifier).email, name="Admin")
        db.rollback()
        current = db.scalar(select(AdminCredential).where(AdminCredential.user_id == identifier))
        assert current.active is active and current.enrollment_expires_at is None
