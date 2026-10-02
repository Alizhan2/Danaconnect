"""Worker eligibility must be reread after waiting for the mentor write lock."""
from datetime import time, timedelta

import pytest
from sqlalchemy import func, select

import app.jobs_calendar as jobs
from app.models import Slot, utcnow
from app.models_calendar import AvailabilityRule


@pytest.mark.parametrize("retirement", ["disabled", "deleted"])
def test_worker_rechecks_rule_after_mentor_lock(integrated_api, monkeypatch, retirement):
    api = integrated_api
    day = utcnow().date() + timedelta(days=1)
    with api.factory() as db:
        rule = AvailabilityRule(mentor_id=api.ids["mentor"], weekday=day.weekday(),
                                start_time=time(9), end_time=time(10), timezone="UTC",
                                slot_minutes=30, starts_on=day, horizon_weeks=1)
        db.add(rule)
        db.commit()
        identifier = rule.id

    original_lock = jobs._lock_users

    def retire_before_lock(db, user_ids):
        # Emulate another committed transaction between the worker's active
        # check and its acquisition of the mentor lock. The separate PG pilot
        # verifies this interleaving with real blocking SELECT FOR UPDATE.
        db.rollback()
        with api.factory() as concurrent:
            stale_rule = concurrent.get(AvailabilityRule, identifier)
            if retirement == "deleted":
                concurrent.delete(stale_rule)
            else:
                stale_rule.active = False
            concurrent.commit()
        return original_lock(db, user_ids)

    original_generate = jobs.generate_rule
    observed_states = []

    def observe_generation(db, current_rule, **kwargs):
        observed_states.append(current_rule.active if current_rule else None)
        return original_generate(db, current_rule, **kwargs)

    monkeypatch.setattr(jobs, "_lock_users", retire_before_lock)
    monkeypatch.setattr(jobs, "generate_rule", observe_generation)
    result = jobs.regenerate_rules(api.factory)
    assert result == {"processed": 0, "created": 0, "skipped": 0, "errors": 0}
    assert observed_states == []
    with api.factory() as db:
        assert db.scalar(select(func.count(Slot.id)).where(Slot.mentor_id == api.ids["mentor"])) == 0
